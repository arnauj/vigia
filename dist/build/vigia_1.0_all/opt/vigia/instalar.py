#!/usr/bin/env python3
"""
VIGIA — Instalador gráfico
Permite elegir entre instalar el servidor (profesor) o el cliente (alumno).
En modo cliente detecta automáticamente la IP del servidor (X.X.X.2).
"""

import os
import socket
import subprocess
import threading
import tkinter as tk
from tkinter import scrolledtext

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR    = os.path.join(SCRIPT_DIR, 'img')

# ── Paleta ─────────────────────────────────────────────────────────────────
BG      = '#0f1117'
CARD    = '#1a1d27'
BORDER  = '#2d3148'
ACCENT  = '#4f8ef7'
TEXT    = '#e2e8f0'
MUTED   = '#718096'
GREEN   = '#48bb78'
RED     = '#fc8181'


def _ip_servidor_defecto():
    """Calcula X.X.X.2 según la interfaz de red activa."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip_local = s.getsockname()[0]
        s.close()
        partes = ip_local.split('.')
        partes[3] = '2'
        return '.'.join(partes)
    except Exception:
        return '192.168.1.2'


class InstaladorVIGIA:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('VIGIA — Instalador')
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self._centrar(540, 660)

        # Icono de ventana
        try:
            self._icon = tk.PhotoImage(
                file=os.path.join(IMG_DIR, 'logo2_mini.png'))
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

        self._build_ui()
        self.root.mainloop()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _centrar(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')

    def _sep(self, parent, pady=12):
        f = tk.Frame(parent, bg=BORDER, height=1)
        f.pack(fill='x', pady=pady)
        return f

    # ── Construcción de la interfaz ──────────────────────────────────────────

    def _build_ui(self):
        # ── Cabecera con logo ──────────────────────────────────────────────
        cab = tk.Frame(self.root, bg=BG)
        cab.pack(fill='x', pady=(22, 0))

        try:
            # logo2.png 768×768 → subsample(5) → ~153×153
            raw = tk.PhotoImage(file=os.path.join(IMG_DIR, 'logo2.png'))
            self._logo = raw.subsample(5, 5)
            tk.Label(cab, image=self._logo, bg=BG).pack()
        except Exception:
            tk.Label(cab, text='VIGIA', font=('Segoe UI', 30, 'bold'),
                     bg=BG, fg=ACCENT).pack()

        tk.Label(cab, text='Sistema de supervisión de aula',
                 font=('Segoe UI', 10), bg=BG, fg=MUTED).pack(pady=(4, 0))

        self._sep(self.root, pady=16)

        # ── Tipo de instalación ────────────────────────────────────────────
        sec = tk.Frame(self.root, bg=BG)
        sec.pack(fill='x', padx=40)

        tk.Label(sec, text='Tipo de instalación:',
                 font=('Segoe UI', 11, 'bold'), bg=BG, fg=TEXT).pack(
            anchor='w', pady=(0, 10))

        self.tipo_var = tk.StringVar(value='servidor')

        radio_kw = dict(
            bg=BG, fg=TEXT, selectcolor=CARD,
            activebackground=BG, activeforeground=TEXT,
            font=('Segoe UI', 10), command=self._on_tipo,
        )
        tk.Radiobutton(sec,
                       text='  🖥   Servidor  —  equipo del profesor',
                       variable=self.tipo_var, value='servidor',
                       **radio_kw).pack(anchor='w', pady=4)
        tk.Radiobutton(sec,
                       text='  💻  Cliente  —  equipo del alumno',
                       variable=self.tipo_var, value='cliente',
                       **radio_kw).pack(anchor='w', pady=4)

        # ── Frame IP (cliente): se inserta/retira antes del sep_prog ───────
        self.frame_ip = tk.Frame(self.root, bg=BG)
        # No se empaqueta todavía; se mostrará al elegir 'cliente'

        tk.Label(self.frame_ip, text='IP del servidor:',
                 font=('Segoe UI', 9), bg=BG, fg=MUTED).pack(
            anchor='w', padx=40, pady=(12, 2))

        self.ip_var = tk.StringVar(value=_ip_servidor_defecto())
        self.ip_entry = tk.Entry(
            self.frame_ip, textvariable=self.ip_var,
            bg=CARD, fg=TEXT, insertbackground=TEXT,
            relief='flat', font=('Segoe UI', 12),
            highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT,
            width=22,
        )
        self.ip_entry.pack(anchor='w', padx=40, ipady=6)

        # ── Separador antes del área de progreso ───────────────────────────
        self.sep_prog = self._sep(self.root, pady=16)

        # ── Área de progreso ───────────────────────────────────────────────
        self.txt = scrolledtext.ScrolledText(
            self.root, width=60, height=10,
            bg='#0a0c14', fg='#88c07a',
            font=('Cascadia Code', 8),
            relief='flat', state='disabled',
        )
        self.txt.pack(padx=20, pady=(0, 10))

        # ── Botones ────────────────────────────────────────────────────────
        btn_row = tk.Frame(self.root, bg=BG)
        btn_row.pack(pady=(4, 22))

        self.btn_instalar = tk.Button(
            btn_row, text='  Instalar  ',
            bg=ACCENT, fg='white',
            font=('Segoe UI', 10, 'bold'),
            relief='flat', cursor='hand2',
            padx=14, pady=7,
            command=self._instalar,
        )
        self.btn_instalar.pack(side='left', padx=8)

        self.btn_cerrar = tk.Button(
            btn_row, text='  Cerrar  ',
            bg=CARD, fg=MUTED,
            font=('Segoe UI', 10),
            relief='flat', cursor='hand2',
            padx=14, pady=7,
            state='disabled',
            command=self.root.destroy,
        )
        self.btn_cerrar.pack(side='left', padx=8)

    # ── Lógica ──────────────────────────────────────────────────────────────

    def _on_tipo(self):
        if self.tipo_var.get() == 'cliente':
            # Insertar frame_ip justo antes del separador de progreso
            self.frame_ip.pack(fill='x', before=self.sep_prog)
        else:
            self.frame_ip.pack_forget()

    def _log(self, text):
        self.txt.config(state='normal')
        self.txt.insert('end', text)
        self.txt.see('end')
        self.txt.config(state='disabled')

    def _instalar(self):
        self.btn_instalar.config(state='disabled')
        tipo = self.tipo_var.get()
        ip   = self.ip_var.get().strip() if tipo == 'cliente' else ''

        if tipo == 'servidor':
            cmd = ['bash', os.path.join(SCRIPT_DIR, 'instalar_servidor.sh')]
            self._log('▶ Instalando VIGIA Servidor…\n\n')
        else:
            script = os.path.join(SCRIPT_DIR, 'instalar_cliente.sh')
            cmd = ['bash', script, ip] if ip else ['bash', script]
            self._log(f'▶ Instalando VIGIA Cliente'
                      f'{" → servidor: " + ip if ip else ""}…\n\n')

        def _run():
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, cwd=SCRIPT_DIR,
                )
                for line in proc.stdout:
                    self.root.after(0, self._log, line)
                proc.wait()
                if proc.returncode == 0:
                    self.root.after(
                        0, self._log, '\n✓ Instalación completada con éxito.\n')
                    self.root.after(0, self._fin, True)
                else:
                    self.root.after(
                        0, self._log,
                        f'\n✗ Error durante la instalación (código {proc.returncode}).\n')
                    self.root.after(0, self._fin, False)
            except Exception as exc:
                self.root.after(0, self._log, f'\n[ERROR] {exc}\n')
                self.root.after(0, self._fin, False)

        threading.Thread(target=_run, daemon=True).start()

    def _fin(self, ok):
        color = GREEN if ok else RED
        self.btn_cerrar.config(state='normal', bg=color, fg='white')
        if not ok:
            self.btn_instalar.config(state='normal')


if __name__ == '__main__':
    InstaladorVIGIA()
