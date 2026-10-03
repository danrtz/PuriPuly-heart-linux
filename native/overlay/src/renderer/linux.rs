use std::sync::Arc;

use cairo::{Context, Format, ImageSurface, LineJoin, Operator};
use pango::{
    Alignment, AttrInt, AttrList, EllipsizeMode, FontDescription, Language, Layout, Weight,
    WrapMode, SCALE,
};

use super::{prepare_layout_for_render, style_bucket_source_counts, RenderedFrame, TextureHandle};
use crate::renderer::cache::BoundedLruCache;
use crate::renderer::font_resolver::{FontLanguageBucket, FontSource, FontWeight, TextStyleKey};
use crate::renderer::layout::CaptionLayoutPolicy;
use crate::renderer::types::*;

#[derive(Clone, PartialEq, Eq, Hash)]
struct LayoutKey {
    text: String,
    language: Option<String>,
    font_size: u32,
    width: u32,
    line_height: u32,
    lines: usize,
}

pub(super) struct LinuxCaptionRenderer {
    surface: ImageSurface,
    context: Context,
    cache: BoundedLruCache<LayoutKey, Layout>,
    previous: Option<ResolvedFrameLayout>,
    last_blocks: Option<(
        Vec<CaptionBlock>,
        CaptionPresentation,
        Option<CaptionDebugOverlay>,
    )>,
    pixels: Arc<Vec<u8>>,
}

impl LinuxCaptionRenderer {
    pub(super) fn new() -> Result<Self, CaptionRenderError> {
        let surface = ImageSurface::create(
            Format::ARgb32,
            DEFAULT_SURFACE_WIDTH_PX as i32,
            DEFAULT_SURFACE_HEIGHT_PX as i32,
        )
        .map_err(draw_error)?;
        let context = Context::new(&surface).map_err(draw_error)?;
        Ok(Self {
            surface,
            context,
            cache: BoundedLruCache::with_capacity(64),
            previous: None,
            last_blocks: None,
            pixels: Arc::new(Vec::new()),
        })
    }

    fn layout(
        &mut self,
        text: &str,
        language: Option<&str>,
        font_size: f32,
        width: f32,
        line_height: f32,
        lines: usize,
    ) -> Layout {
        let key = LayoutKey {
            text: text.into(),
            language: language.map(str::to_owned),
            font_size: font_size.to_bits(),
            width: width.to_bits(),
            line_height: line_height.to_bits(),
            lines,
        };
        if let Some(layout) = self.cache.get(&key) {
            return layout.clone();
        }
        let layout = pangocairo::functions::create_layout(&self.context);
        let mut font = FontDescription::new();
        font.set_family(family(language, text));
        font.set_weight(Weight::Semibold);
        font.set_absolute_size(font_size as f64 * SCALE as f64);
        layout.set_font_description(Some(&font));
        layout
            .context()
            .set_language(language.map(Language::from_string).as_ref());
        layout.set_text(&text.replace(['\n', '\r'], " "));
        layout.set_width((width * SCALE as f32) as i32);
        layout.set_height((line_height * lines as f32 * SCALE as f32).round() as i32);
        layout.set_wrap(WrapMode::WordChar);
        layout.set_ellipsize(EllipsizeMode::End);
        layout.set_alignment(Alignment::Center);
        let attributes = AttrList::new();
        attributes.insert(AttrInt::new_line_height_absolute(
            (line_height * SCALE as f32) as i32,
        ));
        layout.set_attributes(Some(&attributes));
        self.cache.insert(key, layout.clone());
        layout
    }

    pub(super) fn render(
        &mut self,
        policy: &CaptionLayoutPolicy,
        presentation: &CaptionPresentation,
        blocks: Vec<CaptionBlock>,
        width: u32,
        height: u32,
        debug_overlay: Option<CaptionDebugOverlay>,
    ) -> Result<RenderedFrame, CaptionRenderError> {
        let input = (blocks.clone(), presentation.clone(), debug_overlay.clone());
        if self.last_blocks.as_ref() == Some(&input) {
            return Ok(self.frame(self.previous.as_ref().unwrap().clone(), debug_overlay));
        }
        self.context.set_operator(Operator::Clear);
        self.context.paint().map_err(draw_error)?;
        self.context.set_operator(Operator::Over);
        let mut resolved =
            policy.resolve_blocks_for_presentation(blocks.clone(), width, height, presentation);
        let scale = presentation.text_scale.max(0.1);
        for (source, block) in blocks.iter().zip(&mut resolved.visible_blocks) {
            let primary_budget = if block.secondary_reserved { 2 } else { 3 };
            let x = block.bounds.left_px + DEFAULT_STRIP_HORIZONTAL_PADDING_PX as f32;
            let y = block.bounds.top_px;
            let padding = DEFAULT_STRIP_VERTICAL_PADDING_PX as f32 * scale;
            let font_size = DEFAULT_FONT_SIZE_PX * scale;
            let primary = self.layout(
                &source.primary_text,
                source.primary_language.as_deref(),
                font_size,
                block.content_width_px,
                DEFAULT_PRIMARY_LINE_HEIGHT_PX as f32 * scale,
                primary_budget,
            );
            block.truncated_primary = primary.is_ellipsized();
            block.primary_lines = resolved_lines(
                &primary,
                &source.primary_text,
                source.primary_language.as_deref(),
                LineRole::Primary,
                x,
                y + padding * block.render_height_scale,
                font_size,
                block.render_height_scale,
            );
            let secondary_y = padding
                + primary_budget as f32 * DEFAULT_PRIMARY_LINE_HEIGHT_PX as f32 * scale
                + PRIMARY_SECONDARY_GAP_PX * scale;
            let secondary = if source.secondary_enabled && !source.secondary_text.trim().is_empty()
            {
                let layout = self.layout(
                    &source.secondary_text,
                    source.secondary_language.as_deref(),
                    font_size * SECONDARY_FONT_SCALE,
                    block.content_width_px,
                    DEFAULT_SECONDARY_LINE_HEIGHT_PX as f32 * scale,
                    1,
                );
                block.truncated_secondary = layout.is_ellipsized();
                block.secondary_line = resolved_lines(
                    &layout,
                    &source.secondary_text,
                    source.secondary_language.as_deref(),
                    LineRole::Secondary,
                    x,
                    y + secondary_y * block.render_height_scale,
                    font_size * SECONDARY_FONT_SCALE,
                    block.render_height_scale,
                )
                .into_iter()
                .next();
                Some(layout)
            } else {
                block.secondary_line = None;
                None
            };
            self.context.save().map_err(draw_error)?;
            self.context.translate(x as f64, y as f64);
            self.context
                .scale(1.0, block.render_height_scale.max(0.001) as f64);
            self.context.push_group();
            let color = source
                .channel
                .map(|c| fill_color_for_channel(c, source.speaker_style))
                .unwrap_or(SELF_TEXT_FILL_COLOR);
            draw_layout(&self.context, &primary, padding, color)?;
            if let Some(secondary) = secondary {
                draw_layout(&self.context, &secondary, secondary_y, color)?;
            }
            self.context.pop_group_to_source().map_err(draw_error)?;
            self.context
                .paint_with_alpha(source.opacity.clamp(0.0, 1.0) as f64)
                .map_err(draw_error)?;
            self.context.restore().map_err(draw_error)?;
            let (ink, _) = primary.pixel_extents();
            block.visual_bounds = VisualBounds::new(
                block.bounds.left_px,
                block.bounds.top_px - TEXT_OUTLINE_OVERHANG_PX,
                block.bounds.right_px,
                block
                    .bounds
                    .bottom_px
                    .max(y + (padding + ink.height() as f32) * block.render_height_scale)
                    + TEXT_OUTLINE_OVERHANG_PX,
            );
        }
        if let Some(band) = resolved.speaker_divider {
            self.context.set_source_rgba(0.0, 0.0, 0.0, 1.0);
            self.context.rectangle(
                band.left_px as f64,
                band.top_px as f64,
                (band.right_px - band.left_px) as f64,
                (band.bottom_px - band.top_px) as f64,
            );
            self.context.fill().map_err(draw_error)?;
            let band = band.fill_band();
            self.context.set_source_rgba(0.9, 0.9, 0.9, 1.0);
            self.context.rectangle(
                band.left_px as f64,
                band.top_px as f64,
                (band.right_px - band.left_px) as f64,
                (band.bottom_px - band.top_px) as f64,
            );
            self.context.fill().map_err(draw_error)?;
        }
        let fully_transparent =
            !crate::renderer::layout::resolved_layout_has_drawable_text(&resolved);
        let debug_overlay = debug_overlay.filter(|_| !fully_transparent);
        if let Some(debug) = &debug_overlay {
            let layout = self.layout(
                debug.label(),
                Some("en"),
                30.0,
                width as f32 - 32.0,
                42.0,
                2,
            );
            draw_layout(&self.context, &layout, 8.0, (0.4, 1.0, 0.85, 1.0))?;
        }
        self.surface.flush();
        let mut pixels = Vec::new();
        self.surface
            .with_data(|bytes| pixels.extend_from_slice(bytes))
            .map_err(draw_error)?;
        self.pixels = Arc::new(pixels);
        let resolved = prepare_layout_for_render(&mut self.previous, resolved);
        self.last_blocks = Some(input);
        Ok(self.frame(resolved, debug_overlay))
    }

    fn frame(
        &self,
        layout: ResolvedFrameLayout,
        debug_overlay: Option<CaptionDebugOverlay>,
    ) -> RenderedFrame {
        let fully_transparent =
            !crate::renderer::layout::resolved_layout_has_drawable_text(&layout);
        let diagnostics = RenderDiagnostics {
            layout_cache_size: self.cache.len(),
            style_bucket_source_counts: style_bucket_source_counts(&layout),
            ..Default::default()
        };
        RenderedFrame {
            width: layout.surface_width_px,
            height: layout.surface_height_px,
            fully_transparent,
            layout: layout.into(),
            diagnostics,
            texture: TextureHandle::Pixels(self.pixels.clone()),
            debug_overlay,
        }
    }
}

fn family(language: Option<&str>, text: &str) -> &'static str {
    match FontLanguageBucket::for_text(language, text) {
        FontLanguageBucket::CjkKo => "Noto Sans CJK KR, sans-serif",
        FontLanguageBucket::CjkJa => "Noto Sans CJK JP, sans-serif",
        FontLanguageBucket::CjkZhHans => "Noto Sans CJK SC, sans-serif",
        FontLanguageBucket::CjkZhHant => "Noto Sans CJK TC, sans-serif",
        FontLanguageBucket::General => "Noto Sans, sans-serif",
    }
}

fn draw_error(error: impl std::fmt::Display) -> CaptionRenderError {
    CaptionRenderError::Draw(error.to_string())
}

fn draw_layout(
    context: &Context,
    layout: &Layout,
    y: f32,
    color: (f32, f32, f32, f32),
) -> Result<(), CaptionRenderError> {
    context.move_to(0.0, y as f64);
    pangocairo::functions::layout_path(context, layout);
    context.set_line_join(LineJoin::Round);
    context.set_line_width(TEXT_OUTLINE_OVERHANG_PX as f64 * 2.0);
    context.set_source_rgba(0.0, 0.0, 0.0, 1.0);
    context.stroke_preserve().map_err(draw_error)?;
    context.set_source_rgba(
        color.0 as f64,
        color.1 as f64,
        color.2 as f64,
        color.3 as f64,
    );
    context.fill().map_err(draw_error)
}

fn resolved_lines(
    layout: &Layout,
    text: &str,
    language: Option<&str>,
    role: LineRole,
    x: f32,
    y: f32,
    size: f32,
    scale_y: f32,
) -> Vec<ResolvedLineLayout> {
    let bucket = FontLanguageBucket::for_text(language, text);
    let locale = language.unwrap_or("en");
    let family = family(language, text);
    let key = TextStyleKey::from_parts(
        bucket,
        FontSource::SystemFont,
        None,
        family,
        FontWeight::SemiBold,
        locale,
    );
    let mut result = Vec::new();
    let mut iter = layout.iter();
    loop {
        if let Some(line) = iter.line_readonly() {
            let start = line.start_index() as usize;
            let end = (start + line.length() as usize).min(text.len());
            let (ink, logical) = iter.line_extents();
            let units = SCALE as f32;
            result.push(ResolvedLineLayout {
                text: text.get(start..end).unwrap_or("").into(),
                role,
                style_key: key,
                style: TextStyleDescriptor::from_parts(
                    family,
                    FontWeight::SemiBold,
                    locale,
                    FontSource::SystemFont,
                    bucket,
                    key,
                ),
                width_px: logical.width() as f32 / units,
                origin_x: x + logical.x() as f32 / units,
                origin_y: y + logical.y() as f32 / units * scale_y,
                font_size_px: size,
                visual_bounds: VisualBounds::new(
                    x + ink.x() as f32 / units - 5.0,
                    y + ink.y() as f32 / units * scale_y - 5.0,
                    x + (ink.x() + ink.width()) as f32 / units + 5.0,
                    y + (ink.y() + ink.height()) as f32 / units * scale_y + 5.0,
                ),
            });
        }
        if !iter.next_line() {
            break;
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::renderer::CaptionRenderer;

    #[test]
    fn multilingual_pixels_are_visible_and_empty_frame_clears_them() {
        let renderer = CaptionRenderer::new().unwrap();
        let block = CaptionBlock::new("mixed", "Hello • 日本語 • 한국어 • العربية")
            .with_secondary_text("Translation", true);
        let frame = renderer.render_blocks(vec![block]).unwrap();
        let pixels = frame.pixels().unwrap();
        assert!(pixels.chunks_exact(4).any(|p| p[3] != 0));
        assert!(pixels.chunks_exact(4).any(|p| p[3] == 0));
        assert!(!frame.is_fully_transparent());
        assert!(frame.layout().visible_blocks[0].primary_lines.len() <= 2);
        let empty = renderer.render_empty_frame().unwrap();
        assert!(empty.pixels().unwrap().iter().all(|b| *b == 0));
        assert!(empty.is_fully_transparent());
        assert!(pixels.chunks_exact(4).any(|p| p[3] != 0));
    }

    #[test]
    fn explicit_newlines_and_long_words_stay_within_the_caption_budget() {
        let renderer = CaptionRenderer::new().unwrap();
        let block = CaptionBlock::new("long", "A\nB\nC\nD\nE\nF日本語한국어مرحبا".repeat(20));
        let frame = renderer.render_blocks(vec![block]).unwrap();
        let block = &frame.layout().visible_blocks[0];
        assert!(block.truncated_primary);
        assert!(block.primary_lines.len() <= 2);
        assert!(block
            .primary_lines
            .iter()
            .all(|line| line.width_px <= block.content_width_px + 1.0));
    }

    #[test]
    fn unchanged_frames_reuse_pixels() {
        let renderer = CaptionRenderer::new().unwrap();
        let block = CaptionBlock::new("one", "Static text");
        let first = renderer
            .render_blocks(vec![block.clone()])
            .unwrap()
            .pixels()
            .unwrap();
        let second = renderer
            .render_blocks(vec![block])
            .unwrap()
            .pixels()
            .unwrap();
        assert!(Arc::ptr_eq(&first, &second));
    }
}
