from typing import List, Tuple, Any
try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

class InferenceError(Exception):
    pass

def run_inference(image_slice: Any, model_path: str = 'yolov8n.pt', conf_threshold: float = 0.5) -> List[Tuple[int, float, float, float, float, float]]:
    """
    Runs YOLOv8 inference on a single image slice.
    
    Args:
        image_slice: PIL Image or numpy array.
        model_path: Path to the YOLO model file (.pt).
        conf_threshold: Confidence threshold.
        
    Returns:
        List of detections: [(class_id, confidence, x_center, y_center, width, height), ...]
        Coordinates are relative to the slice (pixels).
    """
    if YOLO is None:
        raise InferenceError("ultralytics package is not installed.")
        
    try:
        model = YOLO(model_path)
        # Run inference
        results = model(image_slice, verbose=False, conf=conf_threshold)
        
        detections = []
        for r in results:
            boxes = r.boxes
            for box in boxes:
                # xywh: center_x, center_y, width, height
                x, y, w, h = box.xywh[0].tolist()
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                detections.append((cls, conf, x, y, w, h))
                
        return detections
    except Exception as e:
        raise InferenceError(f"Inference failed: {e}")
