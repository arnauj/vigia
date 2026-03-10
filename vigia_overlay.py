#!/usr/bin/env python3
"""
VIGIA - Pizarra overlay transparente (GTK+Cairo).
Se lanza como subproceso del cliente. Lee comandos JSON de stdin (uno por línea).
Uso: python3 vigia_overlay.py <left> <top> <width> <height>
"""

import sys
import os
import json
import threading
import ctypes
import ctypes.util

os.environ.setdefault('DISPLAY', ':0')
os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')
os.environ.setdefault('GDK_BACKEND', 'x11')

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    import cairo
except Exception as e:
    print(f"[vigia_overlay] GTK no disponible: {e}", file=sys.stderr)
    sys.exit(1)


def _hex_rgb(color):
    c = color.lstrip('#')
    return int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0


def _set_clickthrough(xid):
    """Hace la ventana click-through usando XFixes (input shape vacía)."""
    try:
        x11  = ctypes.cdll.LoadLibrary(ctypes.util.find_library('X11'))
        xfix = ctypes.cdll.LoadLibrary(ctypes.util.find_library('Xfixes'))
        x11.XOpenDisplay.argtypes  = [ctypes.c_char_p]
        x11.XOpenDisplay.restype   = ctypes.c_void_p
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XFlush.argtypes        = [ctypes.c_void_p]
        xfix.XFixesCreateRegion.argtypes         = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        xfix.XFixesCreateRegion.restype          = ctypes.c_ulong
        xfix.XFixesSetWindowShapeRegion.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                                    ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        xfix.XFixesDestroyRegion.argtypes        = [ctypes.c_void_p, ctypes.c_ulong]
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return
        reg = xfix.XFixesCreateRegion(dpy, None, 0)
        xfix.XFixesSetWindowShapeRegion(dpy, ctypes.c_ulong(xid), 2, 0, 0, reg)
        xfix.XFixesDestroyRegion(dpy, reg)
        x11.XFlush(dpy)
        x11.XCloseDisplay(dpy)
        print("[vigia_overlay] click-through activado.", file=sys.stderr)
    except Exception as e:
        print(f"[vigia_overlay] click-through fallido: {e}", file=sys.stderr)


class PizarraOverlay:
    def __init__(self, l, t, w, h):
        self.win = Gtk.Window(type=Gtk.WindowType.POPUP)
        screen = self.win.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.win.set_visual(visual)
        else:
            print("[vigia_overlay] Sin compositor RGBA; fondo puede no ser transparente.", file=sys.stderr)
        self.win.set_app_paintable(True)
        self.win.connect('draw', self._on_draw)
        self.win.move(l, t)
        self.win.resize(w, h)
        self._items = []   # lista de trazos/textos

    def _on_draw(self, _widget, ctx):
        # Limpiar a totalmente transparente
        ctx.set_operator(cairo.OPERATOR_CLEAR)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)
        for item in self._items:
            if item[0] == 'line':
                _, x0, y0, x1, y1, color, size = item
                r, g, b = _hex_rgb(color)
                ctx.set_source_rgba(r, g, b, 1.0)
                ctx.set_line_width(max(1, float(size)))
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                ctx.move_to(float(x0), float(y0))
                ctx.line_to(float(x1), float(y1))
                ctx.stroke()
            elif item[0] == 'text':
                _, x, y, text, color, size = item
                r, g, b = _hex_rgb(color)
                ctx.set_source_rgba(r, g, b, 1.0)
                ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                ctx.set_font_size(max(14, float(size) * 3))
                ctx.move_to(float(x), float(y))
                ctx.show_text(str(text))
        return False

    def show(self):
        self.win.show_all()
        self.win.set_keep_above(True)
        # Aplicar click-through en el siguiente idle (ventana ya mapeada)
        GLib.idle_add(self._apply_clickthrough)

    def _apply_clickthrough(self):
        gdk_win = self.win.get_window()
        if gdk_win:
            _set_clickthrough(gdk_win.get_xid())
        return False

    def hide(self):
        self.win.hide()

    def draw(self, x0, y0, x1, y1, color, size):
        self._items.append(('line', x0, y0, x1, y1, color, size))
        self.win.queue_draw()

    def text(self, x, y, t, color, size):
        self._items.append(('text', x, y, t, color, size))
        self.win.queue_draw()

    def clear(self):
        self._items = []
        self.win.queue_draw()


_ov = None


def _handle(cmd):
    global _ov
    t = cmd.get('type', '')
    if t == 'overlay_toggle':
        if cmd.get('enabled') and _ov:
            _ov.show()
        elif _ov:
            _ov.hide()
    elif t == 'overlay_draw' and _ov:
        _ov.draw(cmd.get('x0', 0), cmd.get('y0', 0),
                 cmd.get('x1', 0), cmd.get('y1', 0),
                 cmd.get('color', '#ff3b30'), cmd.get('size', 6))
    elif t == 'overlay_text' and _ov:
        _ov.text(cmd.get('x', 0), cmd.get('y', 0),
                 cmd.get('text', ''),
                 cmd.get('color', '#ff3b30'), cmd.get('size', 6))
    elif t == 'overlay_clear' and _ov:
        _ov.clear()
    return False  # eliminar del idle_add


def _read_stdin():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            GLib.idle_add(_handle, cmd)
        except Exception:
            pass
    # stdin cerrado → salir
    GLib.idle_add(Gtk.main_quit)


if __name__ == '__main__':
    try:
        l = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        t = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        w = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
        h = int(sys.argv[4]) if len(sys.argv) > 4 else 1080
    except Exception:
        l, t, w, h = 0, 0, 1920, 1080

    _ov = PizarraOverlay(l, t, w, h)
    threading.Thread(target=_read_stdin, daemon=True).start()
    Gtk.main()
