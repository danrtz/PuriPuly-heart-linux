#define _GNU_SOURCE
#include <dlfcn.h>
#include <gtk/gtk.h>

static GtkWidget *with_rgba_visual(GtkWidget *window) {
    GdkVisual *visual = gdk_screen_get_rgba_visual(gtk_widget_get_screen(window));
    if (visual != NULL) {
        gtk_widget_set_visual(window, visual);
        gtk_widget_set_app_paintable(window, TRUE);
    }
    return window;
}

GtkWidget *gtk_window_new(GtkWindowType type) {
    GtkWidget *(*original)(GtkWindowType) = dlsym(RTLD_NEXT, "gtk_window_new");
    return with_rgba_visual(original(type));
}

GtkWidget *gtk_application_window_new(GtkApplication *application) {
    GtkWidget *(*original)(GtkApplication *) = dlsym(RTLD_NEXT, "gtk_application_window_new");
    return with_rgba_visual(original(application));
}

void *fl_view_new(void *project) {
    void *(*original)(void *) = dlsym(RTLD_NEXT, "fl_view_new");
    void (*set_background)(void *, const GdkRGBA *) = dlsym(RTLD_NEXT, "fl_view_set_background_color");
    const GdkRGBA transparent = {0, 0, 0, 0};
    void *view = original(project);
    set_background(view, &transparent);
    return view;
}
