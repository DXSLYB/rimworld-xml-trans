环世界模组 XML ↔ CSV 双向汉化工具

- 提取 XML 中指定标签文本导出为 CSV，方便批量翻译
- 翻译完成后，从 CSV 写回 XML，**保留原版 XML 完整结构**
- 支持单文件处理、递归批量处理整个 Defs 文件夹
- 增加将所有待翻译项目统一导出到指定位置的扩展指令
- 特殊条目 `rulesStrings > li` 单独处理，会导出->后的内容，对多[]提供支持，使用SPLIT_MARKER作为间隔符
- 通过代码内 `TAG_LIBRARY` 控制需要翻译的标签
- 支持存在多{}的条目，导出时转化为*，写入时反向运行
- SPLIT_MARKER标识导出时占位符
- 仅需翻译csv文件的text条目
- 因语言主谓宾等问题，{}与[]位置可能丢失，错位，此部分请自行甄别处理，代码能保证写入的部分，{}[]内容，数量完全一致
- 批量导出未出现CSV的xml文件可能仍然需要翻译
- 批量统一导出单一CSV可能会有剪切板上限，与翻译AI上限问题，谨慎使用

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

#批量导出汇总全部条目到一个总csv
python xmlS-CH.py batch-xml2csv <xml文件夹路径> --single-csv total.csv

#从汇总总csv回写全部xml
python xmlS-CH.py batch-csv2xml <工作文件夹路径> --single-csv total.csv
