#!/usr/bin/env python3
"""
OCR 诊断工具 — 逐层输出截图 + 原始 OCR 结果

用法（微信运行中并选中聊天）：
  .venv/bin/python tools/debug_ocr.py

输出：
  /tmp/wechat_ocr_raw.png      — 原始截图（不裁剪）
  /tmp/wechat_ocr_cropped.png  — 裁剪后截图（实际送入 OCR 的图）
  终端打印每条 OCR 识别结果 + 坐标
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import NSBitmapImageRep, NSImage
from Quartz import (
    CGWindowListCreateImage, CGRectMake,
    kCGWindowListOptionAll, kCGNullWindowID, kCGWindowImageDefault,
)
import Vision

from im_clients.wechat import WechatAdapter


def save_nsimage(ns_img, path: str):
    tiff = ns_img.TIFFRepresentation()
    bitmap = NSBitmapImageRep.imageRepWithData_(tiff)
    png_data = bitmap.representationUsingType_properties_(4, None)
    if png_data:
        png_data.writeToFile_atomically_(path, True)
        print(f"  已保存: {path}  ({os.path.getsize(path)//1024} KB)")
    else:
        print(f"  ❌ 保存失败: {path}")


def capture_raw(bounds):
    x, y, w, h = bounds
    rect = CGRectMake(x, y, w, h)
    cg = CGWindowListCreateImage(
        rect, kCGWindowListOptionAll, kCGNullWindowID, kCGWindowImageDefault
    )
    if cg is None:
        return None
    bitmap = NSBitmapImageRep.alloc().initWithCGImage_(cg)
    print(f"  截图尺寸: {bitmap.pixelsWide()} × {bitmap.pixelsHigh()} px")
    scale = bitmap.pixelsWide() / w
    print(f"  缩放因子: {scale:.1f}x（Retina=2.0，普通=1.0）")
    ns_img = NSImage.alloc().init()
    ns_img.addRepresentation_(bitmap)
    return ns_img, scale


def run_ocr(ns_img) -> list[dict]:
    tiff = ns_img.TIFFRepresentation()
    bitmap = NSBitmapImageRep.imageRepWithData_(tiff)
    png_data = bitmap.representationUsingType_properties_(4, None)
    if png_data is None:
        print("  ❌ PNG 转换失败")
        return []
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(png_data, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(1)            # Accurate
    request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en"])
    request.setUsesLanguageCorrection_(True)
    request.setMinimumTextHeight_(0.01)        # 识别更小的文字
    handler.performRequests_error_([request], None)
    results = list(request.results() or [])
    print(f"  OCR 共识别 {len(results)} 段文字")
    return results


def main():
    adapter = WechatAdapter()
    if not adapter.is_running():
        print("❌ 微信未运行，请先打开微信并选中一个聊天")
        sys.exit(1)

    bounds = adapter._get_window_bounds()
    if bounds is None:
        print("❌ 无法获取微信窗口坐标，请确认微信窗口可见")
        sys.exit(1)

    x, y, w, h = bounds
    print(f"\n📐 微信窗口: x={x:.0f}, y={y:.0f}, w={w:.0f}, h={h:.0f}")

    # ── 1. 原始截图 ─────────────────────────────────────────────
    print("\n【1】截取原始窗口截图（不裁剪）")
    result = capture_raw(bounds)
    if result is None:
        print("  ❌ 截图失败 → 检查屏幕录制权限（系统设置 → 安全性 → 屏幕录制）")
        sys.exit(1)
    ns_raw, scale = result
    save_nsimage(ns_raw, "/tmp/wechat_ocr_raw.png")

    # 检查截图是否全黑（权限问题）
    tiff = ns_raw.TIFFRepresentation()
    bmp = NSBitmapImageRep.imageRepWithData_(tiff)
    pixel = bmp.colorAtX_y_(int(w * scale / 2), int(h * scale / 2))
    brightness = pixel.brightnessComponent() if pixel else -1
    if brightness < 0.01:
        print("  ⚠️  截图中心像素接近全黑，可能是屏幕录制权限未授权")

    # ── 2. 裁剪后截图 ────────────────────────────────────────────
    TOP_SKIP = 50
    BOTTOM_SKIP = 100
    print(f"\n【2】裁剪区域（跳过顶部 {TOP_SKIP}px，底部 {BOTTOM_SKIP}px）")
    crop_h = h - TOP_SKIP - BOTTOM_SKIP
    if crop_h <= 0:
        print(f"  ❌ 裁剪后高度={crop_h:.0f}px，窗口太小，请放大微信窗口")
        sys.exit(1)

    rect = CGRectMake(x, y + TOP_SKIP, w, crop_h)
    cg = CGWindowListCreateImage(
        rect, kCGWindowListOptionAll, kCGNullWindowID, kCGWindowImageDefault
    )
    bitmap = NSBitmapImageRep.alloc().initWithCGImage_(cg)
    ns_crop = NSImage.alloc().init()
    ns_crop.addRepresentation_(bitmap)
    print(f"  裁剪后逻辑尺寸: {w:.0f} × {crop_h:.0f}")
    print(f"  裁剪后像素尺寸: {bitmap.pixelsWide()} × {bitmap.pixelsHigh()}")
    save_nsimage(ns_crop, "/tmp/wechat_ocr_cropped.png")

    # ── 3. OCR 原始结果 ──────────────────────────────────────────
    print("\n【3】OCR 原始识别结果（含坐标，Vision 原点在左下）")
    results = run_ocr(ns_crop)

    if not results:
        print("  ⚠️  未识别到任何文字")
        print("  可能原因：截图区域不含文字 / 文字太小 / 权限问题")
    else:
        print(f"\n  {'文字':<30}  {'x_center':>9}  {'y_top(翻转)':>12}  {'宽':>6}  {'高':>6}")
        print("  " + "-" * 70)
        for obs in results:
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue
            text = candidates[0].string()
            box = obs.boundingBox()
            x_c = box.origin.x + box.size.width / 2
            y_top = 1.0 - (box.origin.y + box.size.height)  # 翻转为左上原点
            side = "→ 我" if x_c > 0.5 else "← 对方"
            print(f"  {repr(text):<30}  {x_c:>9.3f}  {y_top:>12.3f}  {box.size.width:>6.3f}  {box.size.height:>6.3f}  {side}")

    # ── 4. 建议 ──────────────────────────────────────────────────
    print("\n【4】下一步")
    print("  1. 用系统预览打开 /tmp/wechat_ocr_raw.png 确认截图正确")
    print("  2. 打开 /tmp/wechat_ocr_cropped.png 确认裁剪范围合适")
    print("  3. 对比上面的文字识别结果 vs 微信实际聊天内容")
    print("     - 截图全黑  → 系统设置 → 屏幕录制权限授权")
    print("     - 截到标题/输入框 → 调大 _TOP_SKIP/_BOTTOM_SKIP")
    print("     - x_center 分布异常 → 调整 _RIGHT_THRESHOLD")
    print("     - 文字识别有误 → 见 tips")
    print()
    print("  OCR 优化 tips：")
    print("  - 放大微信窗口（更大 = 更高分辨率 = OCR 更准）")
    print("  - 在明亮环境/高对比度主题下使用")


if __name__ == "__main__":
    main()
