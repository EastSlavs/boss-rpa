import pyautogui
import keyboard
import time


def print_position():
    print("工具已启动。将鼠标移动到目标点，按 Ctrl+Q 打印坐标。按 Esc 退出。")
    while True:
        if keyboard.is_pressed('ctrl+q'):
            x, y = pyautogui.position()
            print(f"坐标: ({x}, {y})")
            time.sleep(0.5)
        elif keyboard.is_pressed('esc'):
            break


def slide(start_x, start_y, end_x, end_y, duration=1.0):
    pyautogui.moveTo(start_x, start_y)
    pyautogui.dragTo(end_x, end_y, duration=duration, button='left')


if __name__ == '__main__':
    print_position()

    # slide(100, 800, 100, 300, duration=1.0)
