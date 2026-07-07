import pyautogui
import random
import time
import sys

pyautogui.FAILSAFE = True
CONFIDENCE = 0.9

stats = {'new': 0, 'old': 0}


def get_target_limit():
    while True:
        val = input("请输入目标投递数量 (0-100，直接回车默认50): ").strip()
        if not val:
            return 50
        if val.isdigit():
            num = int(val)
            if 0 <= num <= 100:
                return num
        print("输入无效，请重新输入 0-100 之间的整数。")


def update_console(target):
    print(f"\r[运行统计] 进度: {stats['new']}/{target} | 遇到已沟通: {stats['old']}   ", end='', flush=True)


def add_noise(x, y, offset=6):
    return x + random.randint(-offset, offset), y + random.randint(-offset, offset)


def human_click(x, y):
    nx, ny = add_noise(x, y)
    duration = random.uniform(0.2, 0.4)
    pyautogui.moveTo(nx, ny, duration=duration, tween=pyautogui.easeOutQuad)
    time.sleep(random.uniform(0.1, 0.3))
    pyautogui.click()
    time.sleep(random.uniform(0.1, 0.3))


def human_right_click():
    time.sleep(random.uniform(0.2, 0.4))
    pyautogui.click(button='right')
    time.sleep(random.uniform(0.3, 0.6))


def human_swipe(points=None):
    try:
        top_anchor = pyautogui.locateCenterOnScreen('images/anchor_top_ai.png', confidence=0.85)
    except pyautogui.ImageNotFoundException:
        top_anchor = None

    if points and top_anchor:
        sx, sy = points[-1][0], points[-1][1]
        ex, ey = top_anchor.x, top_anchor.y
    elif points and len(points) >= 2:
        sx, sy = points[-1][0], points[-1][1] - 100
        ex, ey = points[0][0], points[0][1] - 100
    else:
        sx, sy = 2069, 1145
        ex, ey = 2063, 135

    sx, sy = add_noise(sx, sy, offset=15)
    ex, ey = add_noise(ex, ey, offset=15)

    pyautogui.moveTo(sx, sy)
    time.sleep(random.uniform(0.1, 0.2))

    duration = random.uniform(0.8, 1.2)
    pyautogui.dragTo(ex, ey, duration=duration, button='left', tween=pyautogui.easeOutQuad)
    time.sleep(random.uniform(0.5, 1.0))


def filter_unique_targets(targets, threshold=50):
    unique_centers = []
    last_y = -100

    sorted_targets = sorted(targets, key=lambda box: box.top)

    for box in sorted_targets:
        cx, cy = pyautogui.center(box)
        if abs(cy - last_y) > threshold:
            unique_centers.append((cx, cy))
            last_y = cy

    return unique_centers


def handle_detail_page():
    start_time = time.time()

    while time.time() - start_time < 3:
        try:
            chat_now = pyautogui.locateCenterOnScreen('images/btn_chat_now.png', confidence=CONFIDENCE)
            if chat_now:
                human_click(chat_now.x, chat_now.y)
                time.sleep(random.uniform(1.2, 1.8))
                human_right_click()
                time.sleep(random.uniform(0.5, 0.8))
                human_right_click()
                return 'new'
        except pyautogui.ImageNotFoundException:
            pass

        try:
            chat_continue = pyautogui.locateCenterOnScreen('images/btn_chat_continue.png', confidence=CONFIDENCE)
            if chat_continue:
                time.sleep(random.uniform(0.3, 0.6))
                human_right_click()
                return 'old'
        except pyautogui.ImageNotFoundException:
            pass

        time.sleep(0.3)

    human_right_click()
    return 'timeout'


def run():
    target_limit = get_target_limit()
    print("\n系统已启动。强制退出请将鼠标移至屏幕四角。\n")
    update_console(target_limit)

    while stats['new'] < target_limit:
        time.sleep(random.uniform(0.8, 1.5))

        try:
            k_targets = list(pyautogui.locateAllOnScreen('images/target_k.png', confidence=CONFIDENCE))
        except pyautogui.ImageNotFoundException:
            k_targets = []

        if not k_targets:
            human_swipe()
            continue

        unique_points = filter_unique_targets(k_targets)

        for cx, cy in unique_points:
            if stats['new'] >= target_limit:
                break

            human_click(cx, cy)

            time.sleep(random.uniform(1.2, 2.0))
            status = handle_detail_page()

            if status == 'new':
                stats['new'] += 1
            elif status == 'old':
                stats['old'] += 1

            update_console(target_limit)
            time.sleep(random.uniform(0.6, 1.0))

        if stats['new'] < target_limit:
            human_swipe(unique_points)

    print("\n\n[任务完成] 已达到目标投递数量。")


if __name__ == '__main__':
    try:
        run()
    except pyautogui.FailSafeException:
        print("\n\n[终端] 触发安全边界，平滑退出。")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n[终端] 手动终止。")
        sys.exit(0)
