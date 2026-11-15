#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML <-> CSV 双向转换工具（方案A：标签库为 set）
新增：支持 [xxx] 占位符识别翻译中间文本，不再整条跳过含[]的rulesStrings li
新增扩展选项：batch-xml2csv --single-csv 汇总全部条目输出单个总csv
新增扩展选项：batch-csv2xml --single-csv 从总csv批量回写各个xml
改动：
1. 作废：rulesStrings li 翻译侧包含 [ ] 的条目跳过导出与回写；现在[xxx]作为占位符，只翻译中间文本
2. {} / []占位符都作为分割符；被占位符切分的文本片段用*分隔存入text；orig_tokens保存原始token骨架用于复原
3.【新增】无任何可翻译条目时不生成csv文件；导出统计实际生成csv数量
4. source_xml字段：**仅--single‑csv汇总模式才输出**；普通单文件/普通批量不输出该列
5. 修复rulesStrings li val.strip()破坏->后原始空格；过滤->后面全空白的li不导出
用法:
    # 单文件（原有）
    python xmlS-CH.py xml2csv <xml路径> <csv输出路径>
    python xmlS-CH.py csv2xml <csv路径> <xml输出路径> --template 原xml路径
    
    # 批量导出目录下全部xml → 各自生成csv（无翻译条目则跳过生成csv，csv不带source_xml）
    python xmlS-CH.py batch-xml2csv <xml文件夹路径>
    # 批量回写：目录下所有csv写回同名xml，自动使用原xml作为template
    python xmlS-CH.py batch-csv2xml <工作文件夹路径>
        
    # 【新】批量导出汇总全部条目到一个总csv
    python xmlS-CH.py batch-xml2csv <xml文件夹路径> --single-csv total.csv
    # 【新】从汇总总csv回写全部xml
    python xmlS-CH.py batch-csv2xml <工作文件夹路径> --single-csv total.csv
说明:
    只识别/写回 TAG_LIBRARY 中登记的标签；rulesStrings li：[xxx]/{xxx}作为占位符保留，仅翻译普通文本片段
    {}、[]占位符处理：以{xxx}、[xxx]做分割符，文本片段用*分隔保存在text；orig_tokens存储骨架
    库定义在函数内部
    环世界汉化：永远带上 --template，保留原始xml全部结构
"""
import argparse
import csv
import os
import sys
import xml.etree.ElementTree as ET
import re
import json
import io

TAG_LIBRARY = {
    "label",
    "description",
    "resourceDescription",
    "resourceLabel",
    "offsetLabel",
    "jobString",
    "labelNoun",
    "reportString",
}
# rulesStrings 特殊处理开关
ENABLE_RULES_STRINGS = True
SPLIT_MARKER = "*"   # 片段之间分隔符号
# 同时匹配 {xxx} 和 [xxx] 两类占位符
RE_PLACEHOLDER = re.compile(r"(\{.*?\}|\[.*?\])")  #捕获分组 {xxx} 或 [xxx]

def tokenize_curly_text(full_text: str):
    """
    将原始字符串切分token列表，区分【占位符{} / []】和【普通文本片段】
    返回：tokens list；is_placeholder:bool
    例："[RECIPIENT_nameDef] dick was enveloped by [INITIATOR_nameDef] tail."
    → [
        ("[RECIPIENT_nameDef]", True),
        (" dick was enveloped by ", False),
        ("[INITIATOR_nameDef]", True),
        (" tail.", False)
    ]
    """
    raw = RE_PLACEHOLDER.split(full_text)
    tokens = []
    for piece in raw:
        if not piece:
            continue
        if RE_PLACEHOLDER.fullmatch(piece):
            tokens.append((piece, True))
        else:
            tokens.append((piece, False))
    return tokens

def export_split_text(full_text: str):
    """xml->csv：输入完整原文；返回 (joined_text, orig_tokens_json)
    joined_text：普通文本片段用 * 拼接
    orig_tokens_json：json序列化的token骨架，保存占位符位置
    """
    tokens = tokenize_curly_text(full_text)
    text_parts = []
    for txt, is_ph in tokens:
        if not is_ph:
            text_parts.append(txt)
    joined = SPLIT_MARKER.join(text_parts)
    orig_tokens_json = json.dumps(tokens, ensure_ascii=False)
    return joined, orig_tokens_json

def rebuild_from_tokens(orig_tokens_json: str, translated_joined: str):
    """
    csv->xml：使用保存的token骨架 + *分割的翻译文本，重建完整字符串
    orig_tokens_json: token骨架
    translated_joined: csv text列，*分割片段
    """
    try:
        tokens = json.loads(orig_tokens_json)
    except Exception:
        # json解析失败降级，直接返回翻译文本
        return translated_joined
    trans_parts = translated_joined.split(SPLIT_MARKER)
    output = []
    part_idx = 0
    for txt, is_ph in tokens:
        if is_ph:
            # 占位符直接原样输出（[]/{}原样保留）
            output.append(txt)
        else:
            # 普通文本片段，取对应的翻译片段
            if part_idx < len(trans_parts):
                output.append(trans_parts[part_idx])
            else:
                # 翻译片段数量不足，保留原文兜底
                output.append(txt)
            part_idx += 1
    if part_idx != len(trans_parts):
        print(f"[警告]翻译片段数量多于原始文本片段，多余片段丢弃")
    return "".join(output)

def tag_in_library(tag):
    return tag in TAG_LIBRARY

def filter_attrs(tag, attrs):
    if not tag_in_library(tag):
        return {}
    return dict(attrs)

def get_element_path(elem, parent_map):
    """生成元素的唯一路径（基于标签名 + 同级同标签序号）"""
    parts = []
    cur = elem
    while cur is not None:
        parent = parent_map.get(cur)
        if parent is None:
            parts.append(cur.tag)
        else:
            same_tag = [c for c in list(parent) if c.tag == cur.tag]
            if len(same_tag) > 1:
                idx = same_tag.index(cur)
                parts.append(f"{cur.tag}[{idx}]")
            else:
                parts.append(cur.tag)
        cur = parent
    return "/" + "/".join(reversed(parts))

def flatten_xml(root, source_xml_abs_path: str = "", emit_source_xml: bool = False):
    """把 XML 拍平成行，仅处理库内标签 + rulesStrings li；
    emit_source_xml：只有汇总导出模式才True，才写入source_xml字段
    """
    parent_map = {c: p for p in root.iter() for c in p}
    rows = []
    for elem in root.iter():
        # 普通标签
        if tag_in_library(elem.tag):
            orig_text = (elem.text or "").strip("\r\n")
            exp_text, orig_tokens_json = export_split_text(orig_text)
            attrs = filter_attrs(elem.tag, elem.attrib)
            if orig_text == "" and not attrs and len(list(elem)) > 0:
                continue
            path = get_element_path(elem, parent_map)
            row = {
                "path": path,
                "tag": elem.tag,
                "text": exp_text,
                "orig_tokens": orig_tokens_json,
            }
            if emit_source_xml:
                row["source_xml"] = source_xml_abs_path
            for k, v in attrs.items():
                row[f"attr:{k}"] = v
            parent = parent_map.get(elem)
            row["parent_path"] = get_element_path(parent, parent_map) if parent is not None else ""
            rows.append(row)
        # 特殊：rulesStrings > li
        if ENABLE_RULES_STRINGS and elem.tag == "rulesStrings":
            for li in elem.findall("li"):
                li_text = (li.text or "").strip()
                if "->" not in li_text:
                    continue
                key, val = li_text.split("->", 1)
                key = key.strip()
                # FIX：保留 -> 之后原始全部字符，不再 strip(val)
                val_orig = val
                # 过滤：->后面除去空白为空，本条跳过不导出
                if not val_orig.strip():
                    continue
                exp_text, orig_tokens_json = export_split_text(val_orig)
                li_path = get_element_path(li, parent_map)
                row = {
                    "path": li_path,
                    "tag": "rulesString",
                    "text": exp_text,
                    "rs_key": key,
                    "orig_tokens": orig_tokens_json,
                }
                if emit_source_xml:
                    row["source_xml"] = source_xml_abs_path
                parent = parent_map.get(li)
                row["parent_path"] = get_element_path(parent, parent_map) if parent is not None else ""
                rows.append(row)
    return rows

def collect_columns(rows):
    # 根据行内存在key收集
    base_fixed = ["path", "parent_path", "tag", "text", "rs_key", "orig_tokens"]
    seen = set(base_fixed)
    cols = base_fixed.copy()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                cols.append(k)
    return cols

def xml_to_csv(xml_path, csv_path):
    """
    返回值：True=成功生成csv；False=无翻译条目跳过输出
    普通单文件导出：不输出source_xml
    """
    if not os.path.isfile(xml_path):
        raise FileNotFoundError(f"XML 文件不存在: {xml_path}")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    rows = flatten_xml(root, source_xml_abs_path=os.path.abspath(xml_path), emit_source_xml=False)
    if not rows:
        print(f"[跳过] {xml_path}：未识别到可翻译条目，不生成csv")
        return False
    columns = collect_columns(rows)
    out_dir = os.path.dirname(os.path.abspath(csv_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in columns})
    print(f"[OK] 已导出 {len(rows)} 行 -> {csv_path}")
    return True

def csv_to_xml(csv_path, xml_path, template_path=None):
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    if template_path and os.path.isfile(template_path):
        # 推荐分支：基于模板，保留原xml全部结构
        tree = ET.parse(template_path)
        root = tree.getroot()
        path_map = build_path_map(root)
        for r in rows:
            tag = r.get("tag", "")
            path = r.get("path", "")
            elem = path_map.get(path)
            if elem is None:
                print(f"[警告] 模板中找不到路径: {path}，跳过")
                continue
            orig_tokens_json = r.get("orig_tokens", "")
            translated_text = r.get("text", "")
            if tag_in_library(tag):
                # 普通标签，使用token骨架重建完整文本
                final_text = rebuild_from_tokens(orig_tokens_json, translated_text)
                elem.text = final_text
                for k in fieldnames:
                    if k.startswith("attr:"):
                        attr_name = k[len("attr:"):]
                        val = r.get(k, "")
                        if val != "":
                            elem.set(attr_name, val)
                        elif attr_name in elem.attrib:
                            del elem.attrib[attr_name]
            elif tag == "rulesString":
                # rulesStrings li 回写
                rs_key = r.get("rs_key", "")
                final_val = rebuild_from_tokens(orig_tokens_json, translated_text)
                elem.text = f"{rs_key} -> {final_val}"
        # 美化缩进
        try:
            ET.indent(tree, space="\t")
        except AttributeError:
            pass
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        print(f"[OK] 基于模板写回完成 -> {xml_path}")
    else:
        # 无模板重建分支：直接禁用，环世界汉化不需要，避免tree未定义bug
        raise NotImplementedError("不支持无模板重建！环世界汉化必须使用 --template 指定原xml")

def build_path_map(root):
    parent_map = {c: p for p in root.iter() for c in p}
    mapping = {}
    for elem in root.iter():
        mapping[get_element_path(elem, parent_map)] = elem
    return mapping

#批量函数
def batch_xml2csv(folder_path, single_csv_output=None):
    """
    递归：批量导出目录+所有子目录xml
    single_csv_output: 如果不为None，则全部条目汇总到此一个csv文件；否则每个xml输出各自csv
    """
    if not os.path.isdir(folder_path):
        print(f"[错误] 路径不是文件夹：{folder_path}")
        sys.exit(1)
    xml_files = []
    for dirpath, _, filenames in os.walk(folder_path):
        for fname in filenames:
            if fname.lower().endswith(".xml"):
                xml_files.append(os.path.join(dirpath, fname))
    if len(xml_files) == 0:
        print("[提示] 该目录及其子文件夹下没有找到xml文件")
        return
    print(f"[扫描完成] 一共找到 {len(xml_files)} 个xml文件：")
    for f in xml_files:
        print(f"  - {os.path.relpath(f, folder_path)}")
    confirm = input("确认批量导出为csv？输入 y 继续，其他退出：").strip().lower()
    if confirm != "y":
        print("[已取消批量导出]")
        return

    if single_csv_output is not None:
        # 汇总单csv模式：开启emit_source_xml输出来源路径
        all_rows = []
        for xml_fp in xml_files:
            try:
                tree = ET.parse(xml_fp)
                root = tree.getroot()
                rows = flatten_xml(root, source_xml_abs_path=os.path.abspath(xml_fp), emit_source_xml=True)
                if rows:
                    all_rows.extend(rows)
                    print(f"[收集] {os.path.relpath(xml_fp, folder_path)} 读取 {len(rows)} 行")
                else:
                    print(f"[跳过] {os.path.relpath(xml_fp, folder_path)}：无可用翻译条目")
            except Exception as e:
                print(f"[失败] {xml_fp} 读取异常：{e}")
        if not all_rows:
            print("[结束] 全部xml没有任何可翻译条目，不生成汇总csv")
            return
        columns = collect_columns(all_rows)
        out_dir = os.path.dirname(os.path.abspath(single_csv_output))
        os.makedirs(out_dir, exist_ok=True)
        with open(single_csv_output, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for r in all_rows:
                writer.writerow({c: r.get(c, "") for c in columns})
        print(f"\n===== 汇总导出完毕，总 {len(all_rows)} 行 -> {single_csv_output} =====")
    else:
        # 原有逻辑，每个xml输出独立csv，不输出source_xml
        csv_generated_count = 0
        for xml_fp in xml_files:
            base, _ = os.path.splitext(xml_fp)
            csv_fp = base + ".csv"
            try:
                ok = xml_to_csv(xml_fp, csv_fp)
                if ok:
                    csv_generated_count += 1
            except Exception as e:
                print(f"[失败] {xml_fp} 导出异常：{e}")
        print(f"\n===== 批量导出全部执行完毕，实际生成 {csv_generated_count} 个csv文件 =====")


def batch_csv2xml(folder_path, single_csv_input=None):
    """
    递归批量回写
    single_csv_input：不为None代表从汇总总csv回写；否则使用原有同名csv匹配xml模式
    """
    if single_csv_input is not None:
        # 汇总csv回写模式
        if not os.path.isfile(single_csv_input):
            print(f"[错误]汇总csv文件不存在：{single_csv_input}")
            sys.exit(1)
        with open(single_csv_input, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # 按source_xml分组
        groups = {}
        for r in rows:
            src_xml = r.get("source_xml","")
            if not src_xml or not os.path.isfile(src_xml):
                print(f"[警告]该行source_xml无效，跳过：path={r.get('path')}")
                continue
            if src_xml not in groups:
                groups[src_xml] = []
            groups[src_xml].append(r)
        if not groups:
            print("[提示]汇总csv没有有效的source_xml条目，无操作")
            return
        print(f"[扫描完成]汇总csv中将回写 {len(groups)} 个xml文件：")
        for x in groups.keys():
            print(f"  - {os.path.relpath(x, folder_path)}")
        confirm = input("确认从总csv写回xml（会覆盖原xml）？输入 y 继续，其他退出：").strip().lower()
        if confirm != "y":
            print("[已取消批量写回]")
            return
        for xml_abs, row_list in groups.items():
            try:
                # 内存csv，复用现有csv_to_xml逻辑
                output = io.StringIO()
                cols = collect_columns(row_list)
                w = csv.DictWriter(output, fieldnames=cols)
                w.writeheader()
                for rr in row_list:
                    w.writerow({c: rr.get(c,"") for c in cols})
                output.seek(0)
                csv_to_xml(output, xml_abs, template_path=xml_abs)
            except Exception as e:
                print(f"[失败]回写 {xml_abs} 异常：{e}")
        print("\n汇总csv批量回写全部执行完毕")

    else:
        # 原有模式：csv和xml同名配对，不需要source_xml
        pairs = []
        for dirpath, _, filenames in os.walk(folder_path):
            for fname in filenames:
                if fname.lower().endswith(".csv"):
                    csv_fp = os.path.join(dirpath, fname)
                    base, _ = os.path.splitext(csv_fp)
                    xml_fp = base + ".xml"
                    if os.path.isfile(xml_fp):
                        pairs.append((csv_fp, xml_fp))
        if len(pairs) == 0:
            print("[提示] 目录及其子文件夹下没有找到能匹配同名xml的csv")
            return
        print(f"[扫描完成] 一共找到 {len(pairs)} 组可回写的csv+xml：")
        for csv_fp, xml_fp in pairs:
            print(f"  - {os.path.relpath(csv_fp, folder_path)} <-> {os.path.relpath(xml_fp, folder_path)}")
        confirm = input("确认批量写回xml（会覆盖原xml）？输入 y 继续，其他退出：").strip().lower()
        if confirm != "y":
            print("[已取消批量写回]")
            return
        for csv_fp, xml_fp in pairs:
            try:
                csv_to_xml(csv_fp, xml_fp, template_path=xml_fp)
            except Exception as e:
                print(f"[失败] {csv_fp} 写回异常：{e}")
        print("\n批量回写全部执行完毕")

# ------------------------- CLI -------------------------
def main():
    parser = argparse.ArgumentParser(description="XML <-> CSV 双向转换工具 + 批量处理")
    sub = parser.add_subparsers(dest="cmd", required=True)
    # 原有单文件命令
    p1 = sub.add_parser("xml2csv", help="解析 XML 导出库内标签为 CSV")
    p1.add_argument("xml_path", help="输入 XML 文件路径")
    p1.add_argument("csv_path", help="输出 CSV 文件路径")
    p2 = sub.add_parser("csv2xml", help="从 CSV 写回库内标签到 XML（必须带 --template）")
    p2.add_argument("csv_path", help="输入 CSV 文件路径")
    p2.add_argument("xml_path", help="输出 XML 文件路径（可以覆盖原文件）")
    p2.add_argument("--template", default=None, help="【必填】原始XML模板，用来保留结构")
    # 新增批量命令
    p_batch_export = sub.add_parser("batch-xml2csv", help="批量：文件夹下全部xml导出csv，无翻译条目跳过csv")
    p_batch_export.add_argument("folder", help="目标xml文件夹路径")
    p_batch_export.add_argument("--single-csv", default=None, help="可选：输出汇总总csv文件路径，所有条目合并到此文件")

    p_batch_write = sub.add_parser("batch-csv2xml", help="批量：文件夹下csv写回同名xml")
    p_batch_write.add_argument("folder", help="存放csv和xml的文件夹路径")
    p_batch_write.add_argument("--single-csv", default=None, help="可选：读取汇总总csv文件进行批量回写各个xml")

    args = parser.parse_args()
    try:
        if args.cmd == "xml2csv":
            xml_to_csv(args.xml_path, args.csv_path)
        elif args.cmd == "csv2xml":
            if not args.template:
                print("[错误] csv2xml 必须传入 --template 原xml路径！", file=sys.stderr)
                sys.exit(1)
            csv_to_xml(args.csv_path, args.xml_path, args.template)
        elif args.cmd == "batch-xml2csv":
            batch_xml2csv(args.folder, single_csv_output=args.single_csv)
        elif args.cmd == "batch-csv2xml":
            batch_csv2xml(args.folder, single_csv_input=args.single_csv)
    except Exception as e:
        print(f"[错误] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
