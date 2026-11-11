# 현장사진 뷰어: Acrobat 옆에 붙여 쓰는 사진 파일명 목록
# 열려 있는 PDF의 담당자 폴더(예: 김맹신이사)를 찾아 해당 담당자의 크기변환 사진을 날짜별로 나열한다.
# 파일명을 더블클릭(또는 Enter)하면 별도 창에 사진을 띄운다.
# 창은 Acrobat 창 오른쪽에 자동으로 붙고, 프로젝트 폴더는 열려 있는 탐색기 폴더에서 자동으로 찾는다.
import ctypes
import json
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk

from PIL import Image
from PIL import ImageOps
from PIL import ImageTk

DEFAULT_PROJECT_ROOT = r"C:\Users\User\Desktop\김도호\2026\구룡\1015 구룡지하차도 하이퍼링크"
if getattr(sys, "frozen", False):
    # exe로 실행 시: 설정 파일을 exe 옆에 저장 (__file__은 임시 폴더를 가리킴)
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "photo_viewer.json")
PDF_DIR_NAME = "태블릿야장"
PHOTO_DIR_NAME = "현장사진"
RESIZED_DIR_NAME = "크기변환"
IMAGE_EXT = (".jpg", ".jpeg", ".png")
ACROBAT_TITLE = re.compile(r"^\*?\s*(.*\.pdf) - Adobe (Acrobat|Reader)", re.I)
POLL_MS = 300

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SW_RESTORE = 9
DWMWA_EXTENDED_FRAME_BOUNDS = 9
MONITOR_DEFAULTTONEAREST = 2
CREATE_NO_WINDOW = 0x08000000


def natural_key(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def person_name(folder_name):
    # "01. 김맹신이사", "01 김맹신이사" -> "김맹신이사"
    return re.sub(r"^\d+[.\s]*", "", folder_name).strip()


def person_number(folder_name):
    # "01 김맹신이사" -> 1 (직함 순번), 번호 없으면 맨 뒤
    match = re.match(r"^(\d+)", folder_name)
    return int(match.group(1)) if match else 9999


# ---------------- Win32 창 처리 ----------------

def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def pdf_name_from_title(title):
    match = ACROBAT_TITLE.match(title)
    return match.group(1) if match else None


def get_foreground_acrobat():
    # (hwnd, pdf파일명) 또는 (None, None)
    if not IS_WIN:
        return None, None
    hwnd = user32.GetForegroundWindow()
    name = pdf_name_from_title(window_title(hwnd)) if hwnd else None
    return (hwnd, name) if name else (None, None)


def find_acrobat_window():
    found = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and pdf_name_from_title(window_title(hwnd)):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None


def frame_rect(hwnd):
    # 눈에 보이는 창 테두리 (Windows 10/11의 투명 테두리 제외)
    rect = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def move_frame(hwnd, left, top, right, bottom):
    # 보이는 테두리 기준 좌표로 창 이동 (투명 테두리만큼 보정)
    outer = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    fl, ft, fr, fb = frame_rect(hwnd)
    dl, dt, dr, db = fl - outer.left, ft - outer.top, outer.right - fr, outer.bottom - fb
    user32.SetWindowPos(hwnd, None, left - dl, top - dt, (right - left) + dl + dr, (bottom - top) + dt + db, SWP_NOZORDER | SWP_NOACTIVATE)


def work_area(hwnd):
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


# ---------------- 폴더 탐색 ----------------

def find_person_by_pdf(pdf_root, pdf_name):
    for dirpath, _dirs, files in os.walk(pdf_root):
        if pdf_name in files:
            return person_name(os.path.basename(dirpath))
    return None


def list_images(folder):
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    names = [n for n in names if n.lower().endswith(IMAGE_EXT) and os.path.isfile(os.path.join(folder, n))]
    return sorted(names, key=natural_key)


def scan_persons(photo_root):
    # 현장사진/<날짜폴더>/<담당자폴더>/크기변환 구조에서 담당자별 사진 폴더 수집
    # 반환: ({담당자: [(날짜폴더명, 사진폴더경로), ...]}, [담당자 목록 - 폴더 번호순])
    persons = {}
    numbers = {}
    for date_dir in sorted(os.listdir(photo_root), key=natural_key):
        date_path = os.path.join(photo_root, date_dir)
        if not os.path.isdir(date_path):
            continue
        for sub in sorted(os.listdir(date_path), key=natural_key):
            sub_path = os.path.join(date_path, sub)
            if not os.path.isdir(sub_path):
                continue
            resized = os.path.join(sub_path, RESIZED_DIR_NAME)
            folder = resized if os.path.isdir(resized) else sub_path
            name = person_name(sub)
            persons.setdefault(name, []).append((date_dir, folder))
            numbers[name] = min(numbers.get(name, 9999), person_number(sub))
    order = sorted(persons, key=lambda n: (numbers[n], natural_key(n)))
    return persons, order


def is_project_root(path):
    return bool(path) and os.path.isdir(os.path.join(path, PDF_DIR_NAME)) and os.path.isdir(os.path.join(path, PHOTO_DIR_NAME))


def project_root_above(path):
    # path 자신 또는 상위 폴더 중 태블릿야장+현장사진이 있는 폴더
    path = os.path.abspath(path)
    while True:
        if is_project_root(path):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def explorer_folders():
    # 현재 열려 있는 파일 탐색기 창(탭)들의 폴더 경로
    if not IS_WIN:
        return []
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
              "(New-Object -ComObject Shell.Application).Windows() | "
              "ForEach-Object { try { $_.Document.Folder.Self.Path } catch {} }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.decode("utf-8", "ignore").splitlines() if os.path.isdir(line.strip())]


def detect_project_root():
    # 1) 열려 있는 탐색기 폴더의 상위  2) exe가 있는 폴더의 상위
    for folder in explorer_folders() + [APP_DIR]:
        found = project_root_above(folder)
        if found:
            return found
    return None


def load_saved_root():
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f).get("project_root")
        except (OSError, ValueError):
            saved = None
        if is_project_root(saved):
            return saved
    return None


def save_root(path):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"project_root": path}, f, ensure_ascii=False)
    except OSError:
        pass


# ---------------- 화면 ----------------

class Viewer:
    def __init__(self, root, project_root):
        self.root = root
        self.project_root = None
        self.persons = {}
        self.last_pdf = None
        self.popup = None
        self.popup_label = None
        self.photo = None
        self.acro_hwnd = None
        self.last_acro_rect = None

        root.title("현장사진 뷰어")
        root.geometry("340x800")

        top = ttk.Frame(root)
        top.pack(fill="x", padx=4, pady=4)
        self.combo = ttk.Combobox(top, state="readonly", width=14)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self.on_combo)
        ttk.Button(top, text="새로고침", command=self.on_refresh).pack(side="left", padx=4)
        self.snap_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="옆에 붙이기", variable=self.snap_var, command=self.on_snap_toggle).pack(side="left")
        self.status = ttk.Label(root, text="", anchor="w")
        self.status.pack(fill="x", padx=4)
        self.root_label = ttk.Label(root, text="", anchor="w", foreground="#666666")
        self.root_label.pack(fill="x", padx=4)

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree = ttk.Treeview(body, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self.on_open_photo)
        self.tree.bind("<Return>", self.on_open_photo)

        self.set_project_root(project_root)
        self.poll()

    # --- 프로젝트 폴더 ---
    def set_project_root(self, path):
        if path != self.project_root:
            self.project_root = path
            save_root(path)
        self.pdf_root = os.path.join(path, PDF_DIR_NAME)
        self.photo_root = os.path.join(path, PHOTO_DIR_NAME)
        self.root_label.config(text="프로젝트: " + os.path.basename(path))
        self.refresh()

    def redetect_root(self):
        found = detect_project_root()
        if found and found != self.project_root:
            self.set_project_root(found)
            return True
        return False

    def on_refresh(self):
        if not self.redetect_root():
            self.refresh()

    def refresh(self):
        self.persons, order = scan_persons(self.photo_root)
        self.combo["values"] = order
        if self.combo.get() in self.persons:
            self.load_person(self.combo.get())
        else:
            self.combo.set("")
            self.tree.delete(*self.tree.get_children())

    # --- 목록 ---
    def on_combo(self, _event):
        self.load_person(self.combo.get())

    def load_person(self, name):
        self.tree.delete(*self.tree.get_children())
        for date_dir, folder in self.persons.get(name, []):
            files = list_images(folder)
            node = self.tree.insert("", "end", text="%s (%d)" % (date_dir, len(files)), open=True)
            for file_name in files:
                self.tree.insert(node, "end", iid=os.path.join(folder, file_name), text=file_name)

    def on_open_photo(self, _event):
        selected = self.tree.selection()
        if selected and os.path.isfile(selected[0]):
            self.show_photo(selected[0])

    def show_photo(self, path):
        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img)
                img.load()
        except OSError as e:
            messagebox.showerror("사진 열기 실패", "%s\n%s" % (path, e))
            return
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self.root)
            self.popup_label = tk.Label(self.popup, bg="#202020")
            self.popup_label.pack(fill="both", expand=True)
        self.photo = ImageTk.PhotoImage(img)
        self.popup_label.config(image=self.photo)
        self.popup.title(os.path.basename(path))
        self.popup.deiconify()
        self.popup.lift()

    # --- Acrobat 옆에 붙이기 ---
    def on_snap_toggle(self):
        self.last_acro_rect = None

    def snap(self):
        hwnd = self.acro_hwnd
        if not (self.snap_var.get() and hwnd and user32.IsWindow(hwnd)) or user32.IsIconic(hwnd):
            return
        rect = frame_rect(hwnd)
        if rect == self.last_acro_rect:
            return
        own = int(self.root.wm_frame(), 16)
        ol, _ot, orr, _ob = frame_rect(own)
        width = orr - ol
        wl, wt, wr, wb = work_area(hwnd)
        left, top, right, bottom = rect
        if right + width > wr:
            # 오른쪽에 자리가 없으면 Acrobat 폭을 줄여서 자리를 만든다
            if user32.IsZoomed(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
                left, top, bottom = wl, wt, wb
            right = wr - width
            move_frame(hwnd, left, top, right, bottom)
        move_frame(own, right, top, right + width, bottom)
        self.last_acro_rect = frame_rect(hwnd)

    # --- 주기 확인 ---
    def poll(self):
        try:
            hwnd, name = get_foreground_acrobat()
            if hwnd:
                if hwnd != self.acro_hwnd:
                    self.last_acro_rect = None
                self.acro_hwnd = hwnd
            elif IS_WIN and not (self.acro_hwnd and user32.IsWindow(self.acro_hwnd)):
                self.acro_hwnd = find_acrobat_window()
            if IS_WIN:
                self.snap()
            if name and name != self.last_pdf:
                self.last_pdf = name
                self.sync_person(name)
        finally:
            self.root.after(POLL_MS, self.poll)

    def sync_person(self, pdf_name):
        person = find_person_by_pdf(self.pdf_root, pdf_name)
        if not person and self.redetect_root():
            # 다른 프로젝트의 PDF일 수 있으니 탐색기 폴더로 프로젝트를 다시 찾아본다
            person = find_person_by_pdf(self.pdf_root, pdf_name)
        if person and person in self.persons:
            self.combo.set(person)
            self.load_person(person)
            self.status.config(text="PDF 담당자: " + person)
        else:
            self.status.config(text="담당자를 못 찾음 (직접 선택)")


def main():
    if IS_WIN:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.withdraw()
    project_root = detect_project_root() or load_saved_root()
    if not project_root and is_project_root(DEFAULT_PROJECT_ROOT):
        project_root = DEFAULT_PROJECT_ROOT
    if not project_root:
        chosen = filedialog.askdirectory(title="프로젝트 폴더 선택 (태블릿야장, 현장사진이 들어 있는 폴더)")
        project_root = project_root_above(chosen) if chosen else None
    if not project_root:
        messagebox.showerror("폴더 오류", "'%s', '%s' 폴더가 들어 있는 프로젝트 폴더를 찾지 못했습니다.\n해당 폴더를 탐색기로 열어 둔 상태에서 다시 실행하세요." % (PDF_DIR_NAME, PHOTO_DIR_NAME))
        return
    root.deiconify()
    Viewer(root, project_root)
    root.mainloop()


if __name__ == "__main__":
    main()
