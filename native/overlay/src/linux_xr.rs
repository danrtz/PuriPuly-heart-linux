use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context, Result};
use ash::{vk, vk::Handle};
use openxr as xr;

use crate::openvr::{
    OpenVrError, OpenVrRuntimeEvent, OverlayFrameSubmitter, OverlayPlacementPolicy,
    SpatialReanchorOutcome,
};
use crate::renderer::RenderedFrame;
use crate::state::OverlayCalibration;

const WIDTH: u32 = 4096;
const HEIGHT: u32 = 1056;
const FRAME_BYTES: usize = WIDTH as usize * HEIGHT as usize * 4;

#[derive(Default)]
struct SharedState {
    ready: bool,
    stop: bool,
    error: Option<String>,
    pending: Option<(u64, Arc<Vec<u8>>)>,
    submitted: u64,
    uploaded: u64,
    visible: bool,
    observed_visible: bool,
    calibration: OverlayCalibration,
    anchor_generation: u64,
    anchored_generation: u64,
    refresh_hz: Option<f32>,
}

pub(crate) struct LinuxXrOverlay {
    shared: Arc<(Mutex<SharedState>, Condvar)>,
    worker: Option<JoinHandle<()>>,
}

impl LinuxXrOverlay {
    pub(crate) fn new() -> Result<Self, OpenVrError> {
        let shared = Arc::new((Mutex::new(SharedState::default()), Condvar::new()));
        let worker_shared = shared.clone();
        let worker = std::thread::Builder::new()
            .name("puripuly-openxr".into())
            .spawn(move || {
                let outcome = run_overlay(&worker_shared);
                if let Err(error) = &outcome {
                    eprintln!("[overlay][ERROR] OpenXR worker: {error:#}");
                }
                let (lock, changed) = &*worker_shared;
                let mut state = lock.lock().unwrap();
                state.error = Some(match outcome {
                    Ok(()) => "OpenXR overlay session ended".into(),
                    Err(error) => format!("{error:#}"),
                });
                changed.notify_all();
            })
            .map_err(|error| OpenVrError::Init(error.to_string()))?;
        let overlay = Self {
            shared,
            worker: Some(worker),
        };
        let (lock, changed) = &*overlay.shared;
        let state = lock.lock().unwrap();
        let (state, _) = changed
            .wait_timeout_while(state, Duration::from_secs(8), |state| {
                !state.ready && state.error.is_none()
            })
            .unwrap();
        let failure = state.error.clone().or_else(|| {
            (!state.ready).then(|| {
                "OpenXR initialization timed out; start Monadeck/WiVRn and connect your headset"
                    .into()
            })
        });
        drop(state);
        if let Some(error) = failure {
            return Err(OpenVrError::Init(error));
        }
        Ok(overlay)
    }

    fn check_error(state: &SharedState) -> Result<(), OpenVrError> {
        state
            .error
            .as_ref()
            .map_or(Ok(()), |error| Err(OpenVrError::Submit(error.clone())))
    }
}

impl OverlayFrameSubmitter for LinuxXrOverlay {
    fn submit_frame(&mut self, frame: &RenderedFrame) -> Result<(), OpenVrError> {
        let pixels = frame.pixels().ok_or_else(|| {
            OpenVrError::Submit("Linux renderer returned no pixel surface".into())
        })?;
        if frame.width() != WIDTH || frame.height() != HEIGHT || pixels.len() != FRAME_BYTES {
            return Err(OpenVrError::Submit(
                "invalid Linux subtitle surface dimensions".into(),
            ));
        }
        let (lock, changed) = &*self.shared;
        let mut state = lock.lock().unwrap();
        Self::check_error(&state)?;
        state.submitted += 1;
        let sequence = state.submitted;
        state.pending = Some((sequence, pixels));
        changed.notify_all();
        let (state, _) = changed
            .wait_timeout_while(state, Duration::from_secs(2), |state| {
                state.uploaded < sequence && state.error.is_none()
            })
            .unwrap();
        Self::check_error(&state)?;
        if state.uploaded < sequence {
            return Err(OpenVrError::Submit(
                "OpenXR texture upload timed out".into(),
            ));
        }
        Ok(())
    }

    fn apply_calibration(&mut self, calibration: &OverlayCalibration) -> Result<(), OpenVrError> {
        OverlayPlacementPolicy::from_calibration(calibration)?;
        let mut state = self.shared.0.lock().unwrap();
        Self::check_error(&state)?;
        if state.calibration != *calibration {
            state.calibration = calibration.clone();
            state.anchor_generation += 1;
        }
        Ok(())
    }

    fn reanchor_spatial_locked(&mut self) -> Result<SpatialReanchorOutcome, OpenVrError> {
        let (lock, changed) = &*self.shared;
        let mut state = lock.lock().unwrap();
        Self::check_error(&state)?;
        state.anchor_generation += 1;
        let (state, _) = changed
            .wait_timeout_while(state, Duration::from_millis(100), |state| {
                state.anchored_generation != state.anchor_generation && state.error.is_none()
            })
            .unwrap();
        Self::check_error(&state)?;
        Ok(if state.anchored_generation == state.anchor_generation {
            SpatialReanchorOutcome::Applied
        } else {
            SpatialReanchorOutcome::PoseUnavailable
        })
    }

    fn set_overlay_visible(&mut self, visible: bool) -> Result<(), OpenVrError> {
        let mut state = self.shared.0.lock().unwrap();
        Self::check_error(&state)?;
        state.visible = visible;
        Ok(())
    }

    fn observed_overlay_visible(&self) -> Option<bool> {
        Some(self.shared.0.lock().unwrap().observed_visible)
    }

    fn display_refresh_rate_hz(&self) -> Option<f32> {
        self.shared.0.lock().unwrap().refresh_hz
    }

    fn poll_runtime_events(&mut self, max_events: usize) -> Vec<OpenVrRuntimeEvent> {
        if max_events > 0 && self.shared.0.lock().unwrap().error.is_some() {
            vec![OpenVrRuntimeEvent::Quit]
        } else {
            Vec::new()
        }
    }
}

impl Drop for LinuxXrOverlay {
    fn drop(&mut self) {
        self.shared.0.lock().unwrap().stop = true;
        self.shared.1.notify_all();
        if let Some(worker) = self.worker.take() {
            let deadline = Instant::now() + Duration::from_millis(500);
            while !worker.is_finished() && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(5));
            }
            if worker.is_finished() {
                let _ = worker.join();
            }
        }
    }
}

fn run_overlay(shared: &Arc<(Mutex<SharedState>, Condvar)>) -> Result<()> {
    let entry =
        unsafe { xr::Entry::load() }.context("OpenXR loader unavailable (install openxr)")?;
    let available = entry
        .enumerate_extensions()
        .context("OpenXR runtime unavailable; start Monadeck/WiVRn and connect your headset")?;
    if !available.extx_overlay {
        bail!("The active OpenXR runtime does not support XR_EXTX_overlay. Select WiVRn or Monado for VR subtitles; desktop subtitles remain available.");
    }
    if !available.khr_vulkan_enable2 {
        bail!("OpenXR runtime is missing XR_KHR_vulkan_enable2");
    }
    let mut extensions = xr::ExtensionSet::default();
    extensions.extx_overlay = true;
    extensions.khr_vulkan_enable2 = true;
    let instance = entry.create_instance(
        &xr::ApplicationInfo {
            application_name: "PuriPuly Heart Linux",
            application_version: 1,
            engine_name: "PuriPuly",
            engine_version: 1,
            api_version: xr::Version::new(1, 0, 0),
        },
        &extensions,
        &[],
    )?;
    let system = instance
        .system(xr::FormFactor::HEAD_MOUNTED_DISPLAY)
        .context("No connected VR headset; connect it through Monadeck/WiVRn first")?;
    let requirements = instance.graphics_requirements::<xr::Vulkan>(system)?;
    if requirements.min_api_version_supported > xr::Version::new(1, 1, 0) {
        bail!("OpenXR runtime requires a newer Vulkan API than 1.1");
    }
    let gpu = VulkanUpload::new(&instance, system)?;
    let (session, mut waiter, mut stream) = unsafe {
        let raw = create_overlay_session(&instance, system, &gpu.session_info())?;
        xr::Session::<xr::Vulkan>::from_raw(instance.clone(), raw, Box::new(()))
    };
    let local =
        session.create_reference_space(xr::ReferenceSpaceType::LOCAL, xr::Posef::IDENTITY)?;
    let view = session.create_reference_space(xr::ReferenceSpaceType::VIEW, xr::Posef::IDENTITY)?;
    let formats = session.enumerate_swapchain_formats()?;
    let format = [vk::Format::B8G8R8A8_SRGB, vk::Format::R8G8B8A8_SRGB]
        .into_iter()
        .find(|format| formats.contains(&(format.as_raw() as u32)))
        .ok_or_else(|| anyhow!("OpenXR runtime has no sRGB RGBA swapchain format"))?;
    let mut swapchain = session.create_swapchain(&xr::SwapchainCreateInfo {
        create_flags: xr::SwapchainCreateFlags::EMPTY,
        usage_flags: xr::SwapchainUsageFlags::TRANSFER_DST
            | xr::SwapchainUsageFlags::COLOR_ATTACHMENT,
        format: format.as_raw() as u32,
        sample_count: 1,
        width: WIDTH,
        height: HEIGHT,
        face_count: 1,
        array_size: 1,
        mip_count: 1,
    })?;
    let images: Vec<_> = swapchain
        .enumerate_images()?
        .into_iter()
        .map(vk::Image::from_raw)
        .collect();
    let blend_mode = instance
        .enumerate_environment_blend_modes(system, xr::ViewConfigurationType::PRIMARY_STEREO)?
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("OpenXR runtime exposes no environment blend mode"))?;
    let mut event_buffer = xr::EventDataBuffer::new();
    let mut running = false;
    let mut has_image = false;
    let mut last_pixels: Option<Arc<Vec<u8>>> = None;
    let mut anchor_pose = None;
    let mut anchored_generation = 0;
    let startup = Instant::now();
    loop {
        if shared.0.lock().unwrap().stop {
            break;
        }
        while let Some(event) = instance.poll_event(&mut event_buffer)? {
            match event {
                xr::Event::SessionStateChanged(event) => match event.state() {
                    xr::SessionState::READY => {
                        session.begin(xr::ViewConfigurationType::PRIMARY_STEREO)?;
                        running = true;
                        shared.0.lock().unwrap().ready = true;
                        shared.1.notify_all();
                    }
                    xr::SessionState::STOPPING => {
                        session.end()?;
                        running = false;
                    }
                    xr::SessionState::EXITING | xr::SessionState::LOSS_PENDING => return Ok(()),
                    _ => {}
                },
                xr::Event::InstanceLossPending(_) => return Ok(()),
                xr::Event::ReferenceSpaceChangePending(_) => {
                    anchor_pose = None;
                }
                _ => {}
            }
        }
        if !running {
            if !shared.0.lock().unwrap().ready && startup.elapsed() > Duration::from_secs(6) {
                bail!("OpenXR headset session did not become ready");
            }
            std::thread::sleep(Duration::from_millis(10));
            continue;
        }
        let frame = waiter.wait()?;
        stream.begin()?;
        let (pending, visible, calibration, anchor_generation) = {
            let mut state = shared.0.lock().unwrap();
            let period_ns = frame.predicted_display_period.as_nanos();
            if period_ns > 0 {
                state.refresh_hz = Some(1_000_000_000.0 / period_ns as f32);
            }
            (
                state.pending.take(),
                state.visible,
                state.calibration.clone(),
                state.anchor_generation,
            )
        };
        if let Some((sequence, pixels)) = pending {
            if last_pixels
                .as_ref()
                .is_none_or(|previous| !Arc::ptr_eq(previous, &pixels))
            {
                let index = swapchain.acquire_image()? as usize;
                swapchain.wait_image(xr::Duration::from_nanos(500_000_000))?;
                gpu.upload(images[index], &pixels, format)?;
                swapchain.release_image()?;
                last_pixels = Some(pixels);
                has_image = true;
            }
            shared.0.lock().unwrap().uploaded = sequence;
            shared.1.notify_all();
        }
        if calibration.anchor == "spatial_locked"
            && (anchor_pose.is_none() || anchored_generation != anchor_generation)
        {
            let head = view.locate(&local, frame.predicted_display_time)?;
            if head.location_flags.contains(
                xr::SpaceLocationFlags::POSITION_VALID | xr::SpaceLocationFlags::ORIENTATION_VALID,
            ) {
                anchor_pose = spatial_pose(head.pose, &calibration);
                if anchor_pose.is_some() {
                    anchored_generation = anchor_generation;
                    shared.0.lock().unwrap().anchored_generation = anchor_generation;
                    shared.1.notify_all();
                }
            }
        }
        let pose = if calibration.anchor == "spatial_locked" {
            anchor_pose
        } else {
            Some(head_pose(&calibration))
        };
        let shown = visible && frame.should_render && has_image && pose.is_some();
        if shown {
            let width = 1.0667 * calibration.text_scale.max(0.1);
            let layer = xr::CompositionLayerQuad::new()
                .space(if calibration.anchor == "spatial_locked" {
                    &local
                } else {
                    &view
                })
                .eye_visibility(xr::EyeVisibility::BOTH)
                .layer_flags(
                    xr::CompositionLayerFlags::BLEND_TEXTURE_SOURCE_ALPHA
                        | xr::CompositionLayerFlags::UNPREMULTIPLIED_ALPHA,
                )
                .sub_image(
                    xr::SwapchainSubImage::new()
                        .swapchain(&swapchain)
                        .image_array_index(0)
                        .image_rect(xr::Rect2Di {
                            offset: xr::Offset2Di { x: 0, y: 0 },
                            extent: xr::Extent2Di {
                                width: WIDTH as i32,
                                height: HEIGHT as i32,
                            },
                        }),
                )
                .pose(pose.unwrap())
                .size(xr::Extent2Df {
                    width,
                    height: width * HEIGHT as f32 / WIDTH as f32,
                });
            stream.end(frame.predicted_display_time, blend_mode, &[&layer])?;
        } else {
            stream.end(frame.predicted_display_time, blend_mode, &[])?;
        }
        shared.0.lock().unwrap().observed_visible = shown;
    }
    if running {
        let _ = session.request_exit();
    }
    Ok(())
}

fn head_pose(calibration: &OverlayCalibration) -> xr::Posef {
    xr::Posef {
        orientation: xr::Quaternionf::IDENTITY,
        position: xr::Vector3f {
            x: calibration.offset_x,
            y: calibration.offset_y,
            z: -calibration.distance.max(0.1),
        },
    }
}

fn spatial_pose(head: xr::Posef, calibration: &OverlayCalibration) -> Option<xr::Posef> {
    let q = head.orientation;
    let forward = [
        -(2.0 * (q.x * q.z + q.w * q.y)),
        -(2.0 * (q.y * q.z - q.w * q.x)),
        -(1.0 - 2.0 * (q.x * q.x + q.y * q.y)),
    ];
    let length = (forward[0] * forward[0] + forward[2] * forward[2]).sqrt();
    if length < 0.0001 || !length.is_finite() {
        return None;
    }
    let yaw = (-forward[0]).atan2(-forward[2]);
    let right = [-forward[2] / length, 0.0, forward[0] / length];
    let up = [
        -forward[1] * right[2],
        forward[0] * right[2] - forward[2] * right[0],
        forward[1] * right[0],
    ];
    let distance = calibration.distance.max(0.1);
    let mut position = [head.position.x, head.position.y, head.position.z];
    for i in 0..3 {
        position[i] +=
            right[i] * calibration.offset_x + up[i] * calibration.offset_y + forward[i] * distance;
    }
    let pitch = forward[1].asin();
    let (sy, cy) = (yaw * 0.5).sin_cos();
    let (sx, cx) = (pitch * 0.5).sin_cos();
    Some(xr::Posef {
        orientation: xr::Quaternionf {
            x: cy * sx,
            y: sy * cx,
            z: -sy * sx,
            w: cy * cx,
        },
        position: xr::Vector3f {
            x: position[0],
            y: position[1],
            z: position[2],
        },
    })
}

unsafe fn create_overlay_session(
    instance: &xr::Instance,
    system: xr::SystemId,
    info: &xr::vulkan::SessionCreateInfo,
) -> Result<xr::sys::Session> {
    use xr::sys::Handle;
    let overlay = xr::sys::SessionCreateInfoOverlayEXTX {
        ty: xr::sys::SessionCreateInfoOverlayEXTX::TYPE,
        next: std::ptr::null(),
        create_flags: xr::OverlaySessionCreateFlagsEXTX::EMPTY,
        session_layers_placement: 20,
    };
    let binding = xr::sys::GraphicsBindingVulkanKHR {
        ty: xr::sys::GraphicsBindingVulkanKHR::TYPE,
        next: std::ptr::from_ref(&overlay).cast(),
        instance: info.instance,
        physical_device: info.physical_device,
        device: info.device,
        queue_family_index: info.queue_family_index,
        queue_index: info.queue_index,
    };
    let info = xr::sys::SessionCreateInfo {
        ty: xr::sys::SessionCreateInfo::TYPE,
        next: std::ptr::from_ref(&binding).cast(),
        create_flags: xr::SessionCreateFlags::EMPTY,
        system_id: system,
    };
    let mut session = xr::sys::Session::NULL;
    let result = (instance.fp().create_session)(instance.as_raw(), &info, &mut session);
    if result.into_raw() < 0 {
        bail!("creating OpenXR overlay session: {result}");
    }
    Ok(session)
}

struct VulkanUpload {
    _entry: ash::Entry,
    instance: ash::Instance,
    device: ash::Device,
    physical: vk::PhysicalDevice,
    queue_family: u32,
    queue: vk::Queue,
    pool: vk::CommandPool,
    command: vk::CommandBuffer,
    fence: vk::Fence,
    buffer: vk::Buffer,
    memory: vk::DeviceMemory,
}

impl VulkanUpload {
    fn new(xr: &xr::Instance, system: xr::SystemId) -> Result<Self> {
        unsafe {
            let entry = ash::Entry::load()?;
            let get_proc: xr::sys::platform::VkGetInstanceProcAddr =
                std::mem::transmute(entry.static_fn().get_instance_proc_addr);
            let application = vk::ApplicationInfo::default().api_version(vk::API_VERSION_1_1);
            let info = vk::InstanceCreateInfo::default().application_info(&application);
            let raw = xr
                .create_vulkan_instance(system, get_proc, std::ptr::from_ref(&info).cast())?
                .map_err(vk::Result::from_raw)?;
            let instance =
                ash::Instance::load(entry.static_fn(), vk::Instance::from_raw(raw as u64));
            let setup = (|| -> Result<_> {
                let physical =
                    vk::PhysicalDevice::from_raw(xr.vulkan_graphics_device(system, raw)? as u64);
                let queue_family = instance
                    .get_physical_device_queue_family_properties(physical)
                    .iter()
                    .position(|q| q.queue_flags.contains(vk::QueueFlags::GRAPHICS))
                    .ok_or_else(|| anyhow!("GPU exposes no graphics queue"))?
                    as u32;
                let priorities = [1.0];
                let queues = [vk::DeviceQueueCreateInfo::default()
                    .queue_family_index(queue_family)
                    .queue_priorities(&priorities)];
                let info = vk::DeviceCreateInfo::default().queue_create_infos(&queues);
                let raw = xr
                    .create_vulkan_device(
                        system,
                        get_proc,
                        physical.as_raw() as _,
                        std::ptr::from_ref(&info).cast(),
                    )?
                    .map_err(vk::Result::from_raw)?;
                let device =
                    ash::Device::load(instance.fp_v1_0(), vk::Device::from_raw(raw as u64));
                Ok((device, physical, queue_family))
            })();
            let (device, physical, queue_family) = match setup {
                Ok(v) => v,
                Err(error) => {
                    instance.destroy_instance(None);
                    return Err(error);
                }
            };
            let mut gpu = Self {
                _entry: entry,
                instance,
                queue: device.get_device_queue(queue_family, 0),
                device,
                physical,
                queue_family,
                pool: vk::CommandPool::null(),
                command: vk::CommandBuffer::null(),
                fence: vk::Fence::null(),
                buffer: vk::Buffer::null(),
                memory: vk::DeviceMemory::null(),
            };
            gpu.pool = gpu.device.create_command_pool(
                &vk::CommandPoolCreateInfo::default()
                    .queue_family_index(queue_family)
                    .flags(vk::CommandPoolCreateFlags::RESET_COMMAND_BUFFER),
                None,
            )?;
            gpu.command = gpu.device.allocate_command_buffers(
                &vk::CommandBufferAllocateInfo::default()
                    .command_pool(gpu.pool)
                    .level(vk::CommandBufferLevel::PRIMARY)
                    .command_buffer_count(1),
            )?[0];
            gpu.fence = gpu
                .device
                .create_fence(&vk::FenceCreateInfo::default(), None)?;
            gpu.buffer = gpu.device.create_buffer(
                &vk::BufferCreateInfo::default()
                    .size(FRAME_BYTES as u64)
                    .usage(vk::BufferUsageFlags::TRANSFER_SRC)
                    .sharing_mode(vk::SharingMode::EXCLUSIVE),
                None,
            )?;
            let requirements = gpu.device.get_buffer_memory_requirements(gpu.buffer);
            let properties = gpu.instance.get_physical_device_memory_properties(physical);
            let memory_type = (0..properties.memory_type_count)
                .find(|index| {
                    requirements.memory_type_bits & (1 << index) != 0
                        && properties.memory_types[*index as usize]
                            .property_flags
                            .contains(
                                vk::MemoryPropertyFlags::HOST_VISIBLE
                                    | vk::MemoryPropertyFlags::HOST_COHERENT,
                            )
                })
                .ok_or_else(|| anyhow!("GPU has no coherent staging memory"))?;
            gpu.memory = gpu.device.allocate_memory(
                &vk::MemoryAllocateInfo::default()
                    .allocation_size(requirements.size)
                    .memory_type_index(memory_type),
                None,
            )?;
            gpu.device.bind_buffer_memory(gpu.buffer, gpu.memory, 0)?;
            Ok(gpu)
        }
    }

    fn session_info(&self) -> xr::vulkan::SessionCreateInfo {
        xr::vulkan::SessionCreateInfo {
            instance: self.instance.handle().as_raw() as _,
            physical_device: self.physical.as_raw() as _,
            device: self.device.handle().as_raw() as _,
            queue_family_index: self.queue_family,
            queue_index: 0,
        }
    }

    fn upload(&self, image: vk::Image, pixels: &[u8], format: vk::Format) -> Result<()> {
        unsafe {
            let pointer = self.device.map_memory(
                self.memory,
                0,
                FRAME_BYTES as u64,
                vk::MemoryMapFlags::empty(),
            )?;
            let target = std::slice::from_raw_parts_mut(pointer.cast::<u8>(), FRAME_BYTES);
            straight_alpha_pixels(pixels, target, format == vk::Format::R8G8B8A8_SRGB);
            self.device.unmap_memory(self.memory);
            self.device.reset_fences(&[self.fence])?;
            self.device
                .reset_command_buffer(self.command, vk::CommandBufferResetFlags::empty())?;
            self.device.begin_command_buffer(
                self.command,
                &vk::CommandBufferBeginInfo::default()
                    .flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT),
            )?;
            let range = vk::ImageSubresourceRange::default()
                .aspect_mask(vk::ImageAspectFlags::COLOR)
                .level_count(1)
                .layer_count(1);
            let before = vk::ImageMemoryBarrier::default()
                .image(image)
                .subresource_range(range)
                .old_layout(vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL)
                .new_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
                .src_access_mask(vk::AccessFlags::empty())
                .dst_access_mask(vk::AccessFlags::TRANSFER_WRITE)
                .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
                .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED);
            self.device.cmd_pipeline_barrier(
                self.command,
                vk::PipelineStageFlags::TOP_OF_PIPE,
                vk::PipelineStageFlags::TRANSFER,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[before],
            );
            let copy = vk::BufferImageCopy::default()
                .image_subresource(
                    vk::ImageSubresourceLayers::default()
                        .aspect_mask(vk::ImageAspectFlags::COLOR)
                        .layer_count(1),
                )
                .image_extent(vk::Extent3D {
                    width: WIDTH,
                    height: HEIGHT,
                    depth: 1,
                });
            self.device.cmd_copy_buffer_to_image(
                self.command,
                self.buffer,
                image,
                vk::ImageLayout::TRANSFER_DST_OPTIMAL,
                &[copy],
            );
            let after = vk::ImageMemoryBarrier::default()
                .image(image)
                .subresource_range(range)
                .old_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
                .new_layout(vk::ImageLayout::COLOR_ATTACHMENT_OPTIMAL)
                .src_access_mask(vk::AccessFlags::TRANSFER_WRITE)
                .dst_access_mask(
                    vk::AccessFlags::COLOR_ATTACHMENT_READ
                        | vk::AccessFlags::COLOR_ATTACHMENT_WRITE,
                )
                .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
                .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED);
            self.device.cmd_pipeline_barrier(
                self.command,
                vk::PipelineStageFlags::TRANSFER,
                vk::PipelineStageFlags::COLOR_ATTACHMENT_OUTPUT,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[after],
            );
            self.device.end_command_buffer(self.command)?;
            let commands = [self.command];
            let submission = vk::SubmitInfo::default().command_buffers(&commands);
            self.device
                .queue_submit(self.queue, &[submission], self.fence)?;
            self.device
                .wait_for_fences(&[self.fence], true, 500_000_000)
                .context("Vulkan subtitle upload did not complete")?;
        }
        Ok(())
    }
}

impl Drop for VulkanUpload {
    fn drop(&mut self) {
        unsafe {
            let _ = self.device.device_wait_idle();
            self.device.destroy_buffer(self.buffer, None);
            self.device.free_memory(self.memory, None);
            self.device.destroy_fence(self.fence, None);
            self.device.destroy_command_pool(self.pool, None);
            self.device.destroy_device(None);
            self.instance.destroy_instance(None);
        }
    }
}

fn straight_alpha_pixels(source: &[u8], target: &mut [u8], rgba: bool) {
    for (source, target) in source.chunks_exact(4).zip(target.chunks_exact_mut(4)) {
        let alpha = source[3] as u32;
        if alpha == 0 {
            target.fill(0);
            continue;
        }
        for channel in 0..3 {
            let input = if rgba { 2 - channel } else { channel };
            target[channel] = ((source[input] as u32 * 255 + alpha / 2) / alpha).min(255) as u8;
        }
        target[3] = source[3];
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alpha_conversion_preserves_colors_and_zeroes_transparent_rgb() {
        let mut target = [0; 8];
        straight_alpha_pixels(&[16, 32, 64, 128, 9, 9, 9, 0], &mut target, true);
        assert_eq!(target, [128, 64, 32, 128, 0, 0, 0, 0]);
    }

    #[test]
    fn spatial_anchor_keeps_head_position_offsets_and_facing() {
        let head = xr::Posef {
            position: xr::Vector3f {
                x: 2.0,
                y: 1.6,
                z: 3.0,
            },
            ..xr::Posef::IDENTITY
        };
        let calibration = OverlayCalibration {
            offset_x: 0.2,
            offset_y: -0.3,
            distance: 1.1,
            ..Default::default()
        };
        let pose = spatial_pose(head, &calibration).unwrap();
        assert!((pose.position.x - 2.2).abs() < 0.0001);
        assert!((pose.position.y - 1.3).abs() < 0.0001);
        assert!((pose.position.z - 1.9).abs() < 0.0001);
        assert_eq!(pose.orientation, xr::Quaternionf::IDENTITY);
    }
}
