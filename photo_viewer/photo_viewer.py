# 현장사진 뷰어: Acrobat 옆에 붙여 쓰는 사진 파일명 목록
# 열려 있는 PDF의 담당자 폴더(예: 김맹신이사)를 찾아 해당 담당자의 크기변환 사진을 날짜별로 나열한다.
# 파일명을 더블클릭(또는 Enter)하면 별도 창에 사진을 띄운다.
import ctypes
import json
import os
import re
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


def natural_key(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def person_name(folder_name):
    # "01. 김맹신이사", "01 김맹신이사" -> "김맹신이사"
    return re.sub(r"^\d+[.\s]*", "", folder_name).strip()


def get_foreground_pdf_name():
    if sys.platform != "win32":
        return None
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
    match = re.match(r"^\*?\s*(.*\.pdf) - Adobe (Acrobat|Reader)", buf.value, re.I)
    if match:
        return match.group(1)
    return None


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
    # 반환: {담당자: [(날짜폴더명, 사진폴더경로), ...]}
    persons = {}
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
            persons.setdefault(person_name(sub), []).append((date_dir, folder))
    return persons


class Viewer:
    def __init__(self, root, project_root):
        self.root = root
        self.pdf_root = os.path.join(project_root, PDF_DIR_NAME)
        self.photo_root = os.path.join(project_root, PHOTO_DIR_NAME)
        self.persons = {}
        self.last_pdf = None
        self.popup = None
        self.popup_label = None
        self.photo = None

        root.title("현장사진 뷰어")
        root.geometry("340x800")

        top = ttk.Frame(root)
        top.pack(fill="x", padx=4, pady=4)
        self.combo = ttk.Combobox(top, state="readonly", width=16)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self.on_combo)
        ttk.Button(top, text="새로고침", command=self.refresh).pack(side="left", padx=4)
        self.status = ttk.Label(root, text="", anchor="w")
        self.status.pack(fill="x", padx=4)

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree = ttk.Treeview(body, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self.on_open_photo)
        self.tree.bind("<Return>", self.on_open_photo)

        self.refresh()
        self.poll()

    def refresh(self):
        self.persons = scan_persons(self.photo_root)
        self.combo["values"] = sorted(self.persons.keys(), key=natural_key)
        if self.combo.get() in self.persons:
            self.load_person(self.combo.get())

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

    def poll(self):
        name = get_foreground_pdf_name()
        if name and name != self.last_pdf:
            self.last_pdf = name
            person = find_person_by_pdf(self.pdf_root, name)
            if person and person in self.persons:
                self.combo.set(person)
                self.load_person(person)
                self.status.config(text="PDF 담당자: " + person)
            else:
                self.status.config(text="담당자를 못 찾음 (직접 선택)")
        self.root.after(1000, self.poll)


def is_project_root(path):
    return bool(path) and os.path.isdir(os.path.join(path, PDF_DIR_NAME)) and os.path.isdir(os.path.join(path, PHOTO_DIR_NAME))


def load_project_root():
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f).get("project_root")
        if is_project_root(saved):
            return saved
    if is_project_root(DEFAULT_PROJECT_ROOT):
        return DEFAULT_PROJECT_ROOT
    chosen = filedialog.askdirectory(title="프로젝트 폴더 선택 (태블릿야장, 현장사진이 들어 있는 폴더)")
    if is_project_root(chosen):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"project_root": chosen}, f, ensure_ascii=False)
    return chosen


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    root.withdraw()
    project_root = load_project_root()
    if not is_project_root(project_root):
        messagebox.showerror("폴더 오류", "'%s', '%s' 폴더가 들어 있는 프로젝트 폴더를 선택하세요.\n(photo_viewer.json 삭제 후 다시 실행)" % (PDF_DIR_NAME, PHOTO_DIR_NAME))
        return
    root.deiconify()
    Viewer(root, project_root)
    root.mainloop()


if __name__ == "__main__":
    main()
