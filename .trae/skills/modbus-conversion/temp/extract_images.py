import fitz
import os

doc = fitz.open(r'e:\codeGIT\skill\skill-modbus\protocols\BWDK-3206H系列干变温控器说明书(1).pdf')

# Check pages 20-23 for embedded images
for i in range(20, 24):
    page = doc[i]
    print(f'\n===== PAGE {i+1} =====')
    images = page.get_images(full=True)
    print(f'  Embedded images: {len(images)}')
    for img_idx, img in enumerate(images):
        xref = img[0]
        base_image = doc.extract_image(xref)
        img_bytes = base_image['image']
        ext = base_image['ext']
        w = base_image['width']
        h = base_image['height']
        print(f'  Image {img_idx}: xref={xref}, ext={ext}, size={w}x{h}, bytes={len(img_bytes)}')
        
        # Save the image
        out_dir = r'e:\codeGIT\skill\skill-modbus\temp\bwdk_extracted'
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'page{i+1}_img{img_idx}.{ext}')
        with open(out_path, 'wb') as f:
            f.write(img_bytes)
        print(f'    Saved to {out_path}')

doc.close()