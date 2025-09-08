from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_gradient_background(size, start_color, end_color):
    width, height = size
    gradient = Image.new("RGBA", (width, height), color=0)
    draw = ImageDraw.Draw(gradient)

    for i in range(height):
        ratio = i / float(height)
        r = int(start_color[0] * (1 - ratio) + end_color[0] * ratio)
        g = int(start_color[1] * (1 - ratio) + end_color[1] * ratio)
        b = int(start_color[2] * (1 - ratio) + end_color[2] * ratio)
        draw.line([(0, i), (width, i)], fill=(r, g, b, 255))

    return gradient

def apply_image_gradient_to_text(image, position, text, font, gradient_image):
    # 텍스트 크기 계산
    draw = ImageDraw.Draw(image)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    ascent, descent = font.getmetrics()
    text_height = ascent + descent

    # 텍스트 마스크 생성
    text_mask = Image.new("L", (text_width, text_height), 0)
    mask_draw = ImageDraw.Draw(text_mask)
    mask_draw.text((0, 0), text, font=font, fill=255)

    # 그라디언트 이미지 크기를 텍스트 크기에 맞게 조정
    gradient_cropped = gradient_image.resize((text_width, text_height))

    # 텍스트 마스크를 사용하여 그라디언트와 결합
    gradient_text = Image.composite(gradient_cropped, Image.new("RGBA", (text_width, text_height), (0, 0, 0, 0)), text_mask)

    # 원본 이미지에 결합된 텍스트 그라디언트 붙이기
    image.paste(gradient_text, position, text_mask)

def draw_text_with_shadow_and_border(image, position, text, font, shadow_color="black", shadow_offset=(5, 5), shadow_blur_radius=10, border_color="black", border_width=2):
    x, y = position

    # 그림자 레이어 생성
    shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)

    # 그림자를 여러 겹으로 그리면서 흐리게 하기
    for blur_radius in range(shadow_blur_radius, 0, -1):
        alpha = int(255 * (blur_radius / shadow_blur_radius))  # 그림자가 멀어질수록 흐릿하게
        shadow_draw.text((x + shadow_offset[0], y + shadow_offset[1]), text, font=font, fill=(0, 0, 0, alpha))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur_radius))

    # 원본 이미지에 그림자 레이어 추가
    image.paste(shadow_layer, (0, 0), shadow_layer)

    # 테두리(외곽선) 추가
    draw = ImageDraw.Draw(image)
    for dx in range(-border_width, border_width + 1):
        for dy in range(-border_width, border_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=border_color)

    # 본 텍스트 추가
    draw.text(position, text, font=font, fill="white")

def create_image_with_text_gradient_shadow_and_border():
    # 배경 이미지 생성
    img = Image.new("RGBA", (800, 400), (255, 255, 255, 255))

    # 폰트 설정
    font = ImageFont.truetype("arialbd.ttf", size=80)

    # 그라디언트 배경 생성 (예시: 파란색에서 빨간색으로)
    gradient_image = create_gradient_background((800, 400), start_color=(255, 255, 255), end_color=(0, 0, 0))

    # 그림자 및 테두리가 있는 텍스트 그라디언트 추가
    draw_text_with_shadow_and_border(img, position=(50, 50), text="T1 FAKER", font=font, shadow_color="black", shadow_offset=(5, 5), shadow_blur_radius=3, border_color="black", border_width=1)
    draw_text_with_shadow_and_border(img, position=(50, 150), text="AURORA", font=font, shadow_color="black", shadow_offset=(5, 5), shadow_blur_radius=3, border_color="black", border_width=1)
    img.show()
    # 텍스트에 그라디언트 이미지 적용
    apply_image_gradient_to_text(img, position=(50, 50), text="T1 FAKER", font=font, gradient_image=gradient_image)
    apply_image_gradient_to_text(img, position=(50, 150), text="AURORA", font=font, gradient_image=gradient_image)
