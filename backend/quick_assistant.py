import base64
import io
import os
import threading
import tkinter as tk
from tkinter import font
import requests
from PIL import ImageGrab
import keyboard

API_URL = "http://127.0.0.1:8000/quick_vision"

def take_screenshot():
    img = ImageGrab.grab()
    img.thumbnail((1024, 1024))
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def show_popup():
    img_b64 = take_screenshot()

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    
    window_width = 600
    window_height = 200
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width // 2) - (window_width // 2)
    y = (screen_height // 2) - (window_height // 2)
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    root.configure(bg="#0D0C09")
    custom_font = font.Font(family="Segoe UI", size=12)
    
    entry = tk.Entry(root, font=("Segoe UI", 14), bg="#1A1712", fg="#F0E9CE", insertbackground="#F0E9CE", borderwidth=0)
    entry.pack(fill=tk.X, padx=20, pady=(20, 10), ipady=10)
    entry.focus_set()

    result_label = tk.Label(root, text="Ask anything about your screen...", font=custom_font, bg="#0D0C09", fg="#807A6A", wraplength=560, justify="left")
    result_label.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    def close_popup(event=None):
        root.destroy()

    def submit_query(event=None):
        query = entry.get().strip()
        if not query:
            return
            
        entry.config(state="disabled")
        result_label.config(text="Analyzing screen...", fg="#C98A2B")
        root.update()

        def _fetch():
            try:
                r = requests.post(API_URL, json={"prompt": query, "image_b64": img_b64}, timeout=60)
                data = r.json()
                reply = data.get("reply", "Error")
                
                if data.get("saved"):
                    result_label.config(text="ITEM SAVED", fg="#4F7A5A", font=("Segoe UI", 16, "bold"))
                    root.after(1500, close_popup)
                else:
                    result_label.config(text=reply, fg="#F0E9CE", font=("Segoe UI", 12))
            except Exception as e:
                result_label.config(text=f"Connection failed. Is the server running?", fg="#B4574A")

        threading.Thread(target=_fetch, daemon=True).start()

    root.bind("<Return>", submit_query)
    root.bind("<Escape>", close_popup)
    root.after(10, lambda: entry.focus_force())
    root.mainloop()

def main():
    print("Quill Quick Assistant running.")
    print("Press Ctrl+Shift+Q anywhere to capture your screen and ask a question.")
    print("Press Ctrl+C in this terminal to quit.")
    keyboard.add_hotkey('ctrl+shift+q', show_popup)
    keyboard.wait()

if __name__ == "__main__":
    main()
