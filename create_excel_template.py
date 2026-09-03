"""
创建Excel导入模板的辅助脚本
运行此脚本可以生成一个示例Excel文件
"""
import pandas as pd

# 创建示例数据
data = {
    '款号': ['ABC001', 'ABC002', 'ABC003'],
    '文字信息': [
        '产品描述：高品质产品，适用于多种场景',
        '产品描述：经典款式，经久耐用',
        '产品描述：时尚设计，引领潮流'
    ]
}

# 创建DataFrame
df = pd.DataFrame(data)

# 保存为Excel文件
df.to_excel('产品导入模板.xlsx', index=False, engine='openpyxl')

print('Excel模板文件已创建：产品导入模板.xlsx')
print('您可以使用此文件作为导入模板，修改其中的数据后上传。')
