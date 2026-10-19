import io, os, threading, queue, shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
try:
    import pillow_heif; pillow_heif.register_heif_opener()
except Exception:
    pass
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.afc import AfcService

EXT = ('.jpg', '.jpeg', '.heic', '.png', '.dng', '.mov', '.mp4')
THUMB = 96

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("iPhone Photo Transfer (USB)")
        self.geometry("1000x650")
        self.afc = None
        self.items = []            # remote paths
        self.selected = set()
        self.cells = {}            # path -> label
        self.q = queue.Queue()
        self.lock = threading.Lock()

        bar = ttk.Frame(self); bar.pack(fill="x", padx=6, pady=6)
        ttk.Button(bar, text="Connect / Scan", command=self.scan).pack(side="left")
        ttk.Button(bar, text="Select all", command=lambda: self.sel_all(True)).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear", command=lambda: self.sel_all(False)).pack(side="left")
        ttk.Button(bar, text="Copy selected to PC…", command=self.export).pack(side="left", padx=10)
        self.status = ttk.Label(bar, text="Not connected"); self.status.pack(side="left", padx=10)

        wrap = ttk.Frame(self); wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap)
        sb = ttk.Scrollbar(wrap, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_f = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.grid_f, anchor="nw")
        self.grid_f.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self.after(100, self.poll)

    def set_status(self, t): self.q.put(("status", t))

    def scan(self):
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        try:
            self.set_status("Connecting…")
            lockdown = create_using_usbmux()
            self.afc = AfcService(lockdown=lockdown)
            files = []
            for d in sorted(self.afc.listdir("DCIM")):
                if d in (".", ".."): continue
                p = f"DCIM/{d}"
                if self.afc.isdir(p):
                    for f in sorted(self.afc.listdir(p)):
                        if f.lower().endswith(EXT):
                            files.append(f"{p}/{f}")
            self.items = files[::-1]   # newest-looking first
            self.q.put(("build", None))
            self.set_status(f"{len(files)} files found")
            for path in self.items:
                if not path.lower().endswith(('.jpg', '.jpeg', '.heic', '.png')): continue
                try:
                    with self.lock:
                        data = self.afc.get_file_contents(path)
                    im = Image.open(io.BytesIO(data)); im.thumbnail((THUMB, THUMB))
                    self.q.put(("thumb", (path, im)))
                except Exception:
                    pass
        except Exception as e:
            self.q.put(("error", str(e)))

    def build(self):
        for w in self.grid_f.winfo_children(): w.destroy()
        self.cells.clear(); self.selected.clear()
        cols = 8
        for i, p in enumerate(self.items):
            lb = tk.Label(self.grid_f, text=os.path.basename(p), compound="top",
                          width=THUMB // 7 + 2, wraplength=THUMB + 10, relief="flat", bd=3)
            lb.grid(row=i // cols, column=i % cols, padx=3, pady=3)
            lb.bind("<Button-1>", lambda e, p=p: self.toggle(p))
            self.cells[p] = lb

    def toggle(self, p):
        if p in self.selected: self.selected.discard(p); self.cells[p].config(relief="flat", bg="SystemButtonFace")
        else: self.selected.add(p); self.cells[p].config(relief="solid", bg="#9ad0ff")
        self.set_status(f"{len(self.selected)} selected")

    def sel_all(self, on):
        for p in self.items:
            if (p in self.selected) != on: self.toggle(p)

    def export(self):
        if not self.selected:
            return messagebox.showinfo("Nothing selected", "Click photos to select them first.")
        dest = filedialog.askdirectory(title="Save to…")
        if dest:
            threading.Thread(target=self._export, args=(dest, sorted(self.selected)), daemon=True).start()

    def _export(self, dest, paths):
        try:
            for i, p in enumerate(paths, 1):
                self.set_status(f"Copying {i}/{len(paths)}: {os.path.basename(p)}")
                with self.lock:
                    data = self.afc.get_file_contents(p)
                with open(os.path.join(dest, os.path.basename(p)), "wb") as f:
                    f.write(data)
            self.set_status(f"Done: {len(paths)} files copied to {dest}")
        except Exception as e:
            self.q.put(("error", str(e)))

    def poll(self):
        try:
            while True:
                k, v = self.q.get_nowait()
                if k == "status": self.status.config(text=v)
                elif k == "build": self.build()
                elif k == "thumb":
                    p, im = v
                    if p in self.cells:
                        ph = ImageTk.PhotoImage(im); self.cells[p].image = ph
                        self.cells[p].config(image=ph)
                elif k == "error": messagebox.showerror("Error", v); self.status.config(text="Error")
        except queue.Empty:
            pass
        self.after(100, self.poll)

App().mainloop()
