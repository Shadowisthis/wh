from ultralytics import YOLO
import cv2
import os

model = YOLO('best.pt')

def predict_pneumonia(image_path):
    # 确保结果目录存在
    os.makedirs("static/results", exist_ok=True)
    
    # 进行推理
    results = model(image_path)
    result = results[0]
    
    # 处理结果图像
    output_img = result.plot()
    
    # 生成安全文件名
    base_name = os.path.basename(image_path)
    file_name, ext = os.path.splitext(base_name)
    output_filename = f"{file_name}_result{ext}"
    output_path = os.path.join("static/results", output_filename)
    
    # 保存结果图像
    cv2.imwrite(output_path, cv2.cvtColor(output_img, cv2.COLOR_RGB2BGR))
    
    # 收集统计信息
    confidence_list = result.boxes.conf.tolist() if result.boxes else []
    statistics = {
        '诊断结果': '肺炎阳性' if len(result.boxes) > 0 else '正常',
        '最大置信度': f"{max(confidence_list, default=0):.2%}",
        '平均置信度': f"{sum(confidence_list)/len(confidence_list):.2%}" if confidence_list else "0%",
        '病灶数量': len(result.boxes)
    }
    
    return output_path, statistics