from typing import Generator, Tuple
from PIL import Image

from agri_guard_core.pil_open import open_image


def slice_image(image_path: str, tile_size: int = 1024, overlap: float = 0.2) -> Generator[Tuple[Image.Image, int, int], None, None]:
    """
    Slices a large image into smaller tiles with overlap.
    
    Args:
        image_path: Path to the source image.
        tile_size: Size of the square tile (default 1024).
        overlap: Overlap percentage (0.0 to 1.0, default 0.2).
        
    Yields:
        (tile_image, offset_x, offset_y)
    """
    # Keep the source file open only while iterating; avoids FD leaks on large batches.
    with open_image(image_path) as img:
        width, height = img.size

        stride = int(tile_size * (1 - overlap))

        for y in range(0, height, stride):
            for x in range(0, width, stride):
                real_x = x
                real_y = y

                if real_x + tile_size > width:
                    real_x = max(0, width - tile_size)
                if real_y + tile_size > height:
                    real_y = max(0, height - tile_size)

                box = (real_x, real_y, real_x + tile_size, real_y + tile_size)
                tile = img.crop(box)

                yield tile, real_x, real_y

                if real_x + tile_size >= width:
                    break
            if real_y + tile_size >= height:
                break
