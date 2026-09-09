import fitz
import json

doc = fitz.open(r'e:\codeGIT\skill\skill-modbus\protocols\BWDK-3206H系列干变温控器说明书(1).pdf')

# Check pages 20-23 (0-indexed) - the RS485 section
for i in range(20, 24):
    page = doc[i]
    print(f'\n===== PAGE {i+1} (index {i}) =====')
    
    # Try words extraction
    words = page.get_text('words')
    if words:
        print('WORDS:')
        for w in words:
            print(f'  {w}')
    
    # Try dict extraction
    d = page.get_text('dict')
    print(f'Blocks count: {len(d["blocks"])}')
    for b_idx, block in enumerate(d['blocks']):
        if 'lines' in block:
            for l_idx, line in enumerate(block['lines']):
                for s_idx, span in enumerate(line['spans']):
                    txt = span['text']
                    font = span.get('font', '?')
                    size = span.get('size', '?')
                    print(f'  Block {b_idx}, Line {l_idx}, Span {s_idx}: text="{txt}", font={font}, size={size}')
        elif 'image' in block:
            w = block.get('width', '?')
            h = block.get('height', '?')
            print(f'  Block {b_idx}: IMAGE, size={w}x{h}')

doc.close()