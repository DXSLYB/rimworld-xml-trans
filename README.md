# rimworld-xml-trans
环世界模组 XML ↔ CSV 双向汉化工具

- 提取 XML 中指定标签文本导出为 CSV，方便批量翻译
- 翻译完成后，从 CSV 写回 XML，**保留原版 XML 完整结构**
- 支持单文件处理、递归批量处理整个 Defs 文件夹
- 特殊条目 `rulesStrings > li` 单独处理，逻辑不改动
- 通过代码内 `TAG_LIBRARY` 控制需要翻译的标签
- 本人运行运行时python3.13

使用方法
> 脚本文件名：`xmlS-CH.py`

### 单文件模式
```bash
# XML 导出 CSV
python xmlS-CH.py xml2csv <xml路径> <csv输出路径>

# CSV 写回 XML（环世界汉化必须指定 template，保留原始结构）
python xmlS-CH.py csv2xml <csv路径> <xml输出路径> --template 原xml路径

# 批量导出：文件夹下所有 XML 各自生成同名 CSV
python xmlS-CH.py batch-xml2csv <xml文件夹路径>

# 批量回写：文件夹下 CSV 写回同名 XML，自动使用原 XML 作为 template
python xmlS-CH.py batch-csv2xml <工作文件夹路径>

