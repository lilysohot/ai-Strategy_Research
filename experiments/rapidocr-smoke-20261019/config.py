from rapidocr import ModelType, OCRVersion


def params(size):
    return {
        'Det.model_type': ModelType(size),
        'Rec.model_type': ModelType(size),
        'Det.ocr_version': OCRVersion.PPOCRV6,
        'Rec.ocr_version': OCRVersion.PPOCRV6,
        'Global.model_root_dir': '/opt/ocr-models',
        'Global.log_level': 'warning',
        'EngineConfig.onnxruntime.intra_op_num_threads': 1,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
    }
