import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def get_contrast_color_from_background(bg_frame, points, threshold=130):
    """
    根据多边形区域平均亮度返回柔和的高对比颜色
    - 背景亮度高，返回深灰
    - 背景亮度低，返回淡灰
    """
    if not points or len(points) < 3:
        return (50, 50, 50)  # 默认深灰

    # 创建空白 mask
    mask = np.zeros(bg_frame.shape[:2], dtype=np.uint8)
    pts = np.array(points, np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(mask, [pts], 255)

    # 提取区域像素
    region = cv2.bitwise_and(bg_frame, bg_frame, mask=mask)
    b, g, r = cv2.split(region)
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    # 平均亮度
    avg_lum = lum[mask > 0].mean() if np.any(mask > 0) else threshold

    # 返回柔和高对比色
    if avg_lum > threshold:
        return (0, 0, 0)  # 深灰
    else:
        return (255, 255, 255)  # 淡灰


def draw_fence_with_text(bg_frame, fence_points, text_list, font_path=None, font_size=24, line_spacing=1.2, base_height=1080):
    """
    在图像上绘制围栏和多行文字，生成透明底图
    文字颜色根据背景亮度自动选择黑/白
    支持 BGR / BGRA 图像
    绘制参数根据背景图高度按比例缩放
    参数：
    - bg_frame: np.ndarray, 背景图像，用于颜色对比
    - fence_points: list of (x, y) 围栏顶点
    - text_list: list of str，每行文字
    - font_path: str, 字体文件路径（None使用默认）
    - font_size: int, 基于 base_height 的字体大小
    - line_spacing: float, 行距倍数
    - base_height: int, 基准高度（默认 1080p）
    """

    if not fence_points or len(fence_points) < 3:
        return np.zeros((*bg_frame.shape[:2], 4), dtype=np.uint8)

    # -----------------------------
    # 缩放比例
    scale = bg_frame.shape[0] / base_height

    # 绘制参数按比例缩放
    scaled_font_size = max(1, int(font_size * scale))
    line_thickness = max(1, int(2 * scale))        # 原 2
    point_radius = max(1, int(4 * scale))          # 原 4

    # -----------------------------
    # 创建透明底图
    frame = np.zeros((*bg_frame.shape[:2], 4), dtype=np.uint8)

    # -----------------------------
    # 1. 绘制围栏
    pts = np.array(fence_points, np.int32).reshape((-1, 1, 2))
    color = get_contrast_color_from_background(bg_frame, fence_points)

    overlay = np.zeros_like(frame, dtype=np.uint8)
    cv2.polylines(overlay, [pts], isClosed=True, color=(*color, 255),
                  thickness=line_thickness, lineType=cv2.LINE_AA)

    for (x, y) in fence_points:
        cv2.circle(overlay, (x, y), radius=point_radius, color=(*color, 255), thickness=-1, lineType=cv2.LINE_AA)

    mask = overlay[:, :, 3] > 0
    frame[mask] = overlay[mask]

    # -----------------------------
    # 2. 绘制文字
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA))
    draw = ImageDraw.Draw(pil_img)

    font = ImageFont.truetype(font_path, scaled_font_size) if font_path else ImageFont.load_default()

    xs, ys = zip(*fence_points)
    center_x = int(sum(xs) / len(xs))
    center_y = int(sum(ys) / len(ys))

    line_heights = [font.getbbox(line)[3] - font.getbbox(line)[1] for line in text_list]
    total_height = int(sum(line_heights) * line_spacing)

    y0 = center_y - total_height // 2
    for i, line in enumerate(text_list):
        bbox = font.getbbox(line)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = center_x - w // 2
        y = y0 + int(sum(line_heights[:i]) * line_spacing)
        draw.text((x, y), line, font=font, fill=color[::-1])

    frame = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGBA2BGRA)
    return frame


def generate_fence_layer_blur(bg_frame, fence_points, text_list, font_path=None, font_size=24, line_spacing=1.2, blur_ksize=500):
    """
    生成透明底的围栏/文字图层。
    内容颜色取背景反转灰度，并先对背景进行高斯模糊。
    """
    h, w = bg_frame.shape[:2]

    # 自动修正 blur_ksize 为奇数且合理大小
    blur_ksize = max(1, blur_ksize)
    if blur_ksize % 2 == 0:
        blur_ksize += 1

    # 限制核大小不能超过图像尺寸（否则会报另一个错误）
    blur_ksize = min(blur_ksize, min(h, w) | 1)  # 确保为奇数

    # 1. 背景高斯模糊
    blurred_bg = cv2.GaussianBlur(bg_frame, (blur_ksize, blur_ksize), 0)

    # 2. 黑底遮罩
    mask = np.zeros((h, w), dtype=np.uint8)

    # 绘制围栏
    pts = np.array(fence_points, np.int32).reshape((-1, 1, 2))
    cv2.polylines(mask, [pts], isClosed=True, color=255, thickness=2)
    for (x, y) in fence_points:
        cv2.circle(mask, (x, y), radius=4, color=255, thickness=-1)

    # 绘制文字
    pil_mask = Image.fromarray(mask)
    draw = ImageDraw.Draw(pil_mask)
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    xs, ys = zip(*fence_points)
    center_x, center_y = int(sum(xs) / len(xs)), int(sum(ys) / len(ys))
    line_heights = [font.getbbox(line)[3] - font.getbbox(line)[1] for line in text_list]
    total_height = int(sum(line_heights) * line_spacing)
    y0 = center_y - total_height // 2

    for i, line in enumerate(text_list):
        bbox = font.getbbox(line)
        w_line = bbox[2] - bbox[0]
        x = center_x - w_line // 2
        y = y0 + int(sum(line_heights[:i]) * line_spacing)
        draw.text((x, y), line, font=font, fill=255)

    mask = np.array(pil_mask)

    # 3. 高斯模糊后的灰度图并反转
    gray_blur = cv2.cvtColor(blurred_bg, cv2.COLOR_BGR2GRAY)
    inverted = 255 - gray_blur

    # 4. 生成透明图层（BGRA）
    layer = np.zeros((h, w, 4), dtype=np.uint8)
    layer[mask > 0, 0] = inverted[mask > 0]  # B
    layer[mask > 0, 1] = inverted[mask > 0]  # G
    layer[mask > 0, 2] = inverted[mask > 0]  # R
    layer[mask > 0, 3] = 255  # A

    return layer


# 全局变量存储点击的点
clicked_points = []


def mouse_callback(event, x, y, flags, param):
    global clicked_points
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"点击坐标: ({x}, {y})")
        clicked_points.append((x, y))


def test_draw_fence_with_text_interactive():
    global clicked_points
    clicked_points = []

    # 1. 读取测试图像
    bg_frame = cv2.imread('2.png', cv2.IMREAD_COLOR)
    if bg_frame is None:
        raise FileNotFoundError("背景图无法读取，请检查路径")

    clone = bg_frame.copy()
    cv2.namedWindow("点击获取坐标")
    cv2.setMouseCallback("点击获取坐标", mouse_callback)

    print("请点击围栏顶点（按 'q' 退出）")

    while True:
        # 在图上绘制已点击的点
        display = clone.copy()
        for pt in clicked_points:
            cv2.circle(display, pt, 5, (0, 0, 255), -1)
        cv2.imshow("点击获取坐标", display)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break

    cv2.destroyAllWindows()

    if len(clicked_points) < 3:
        print("至少需要3个点形成围栏")
        return

    # 2. 定义多行文字
    text_list = ["测试区域", "请勿靠近", "Hello World"]

    # 3. 绘制最终图像
    from watermark_utils import draw_fence_with_text  # 引入你原来的函数
    result_frame = draw_fence_with_text(
        bg_frame,
        clicked_points,
        text_list,
        font_path="C:/Windows/Fonts/msyh.ttc",
        font_size=24,
        line_spacing=1.2
    )

    # 4. 保存结果
    cv2.imwrite("test_fence_output.png", result_frame)
    print("绘制完成图片已保存：test_fence_output.png")

    # 5. 可视化叠加
    alpha = 0.6
    if result_frame.shape[2] == 4:
        overlay_rgb = cv2.cvtColor(result_frame, cv2.COLOR_BGRA2BGR)
        alpha_mask = result_frame[:, :, 3] / 255.0
        alpha_mask = alpha_mask[:, :, np.newaxis]
        overlay_img = (overlay_rgb * alpha_mask + bg_frame * (1 - alpha_mask)).astype(np.uint8)
    else:
        overlay_img = cv2.addWeighted(result_frame, alpha, bg_frame, 1 - alpha, 0)

    cv2.imwrite("test_fence_overlay.png", overlay_img)
    print("叠加可视化图片已保存：test_fence_overlay.png")


# 执行测试
if __name__ == "__main__":
    test_draw_fence_with_text_interactive()
