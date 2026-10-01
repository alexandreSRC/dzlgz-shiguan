import base64
import json
import os
import re
import logging

try:
    import requests
except ImportError:
    # 允许在没有 requests 的环境下启动主程序，仅 AI 识别功能不可用
    requests = None

logger = logging.getLogger(__name__)

REQUESTS_MISSING_MSG = "缺少 requests 库，无法调用 API。请在 cmd 执行：python -m pip install requests"

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"   # 留档：deepseek-chat 不支持图像输入（A14）
DOUBAO_API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "deepseek-chat"
DOUBAO_VISION_MODEL = "doubao-seed-1-6-vision-250815"
CONFIG_FILE = "config.json"

_OCR_READER = None

def _get_ocr_reader():
    global _OCR_READER
    if _OCR_READER is None:
        try:
            import easyocr
        except ImportError:
            raise RuntimeError(
                "缺少 easyocr 库，本地OCR不可用。请在 cmd 执行：python -m pip install easyocr"
            )
        logger.info("正在加载 OCR 模型（首次使用需下载，约 200MB）...")
        try:
            _OCR_READER = easyocr.Reader(['ch_sim', 'en'], gpu=True)
        except Exception as e:
            # 没有可用的 CUDA 环境时退回 CPU 模式
            logger.warning(f"GPU 模式加载 OCR 失败({e})，改用 CPU 模式")
            _OCR_READER = easyocr.Reader(['ch_sim', 'en'], gpu=False)
        logger.info("OCR 模型加载完成")
    return _OCR_READER


DETECTION_PROMPT = """你是游戏"大周列国志"的新生儿信息识别专家。

我将给你一张游戏截图，截图中包含每年的新生儿信息（贤士出生界面）。
请仔细识别截图中所有的生子记录信息（仅识别儿子，不识别女儿）。

截图中的信息格式为：
- "XXX新得一子，名曰 XXX"
- 子名后面可能跟有年份信息如"天智XX"

请按以下JSON格式返回所有识别到的记录，不要遗漏：
[
  {
    "year": "年份文本，如'天智69'",
    "father": "父亲的名字",
    "mother": "",
    "child": "孩子的名字",
    "gender": "男"
  }
]

要求：
1. 只识别明确的生子（儿子）记录，忽略生女记录
2. 不要遗漏任何一条生子记录
3. 如果没有找到任何生子信息，返回空数组 []
4. 只返回JSON格式，不要添加任何其他文字说明"""


class AIDetector:
    def __init__(self, api_key=None, model=DEFAULT_MODEL, provider="deepseek"):
        self.api_key = api_key
        self.model = model
        self.provider = provider.lower()
        # ★ 代码改进 A14：只有豆包视觉模型支持图像识别；DeepSeek 的对话模型
        #   不吃图，那条路径必然 API 报错 —— 统一走豆包端点，非豆包在
        #   analyze_single 入口直接给可读错误。
        self.api_base = DOUBAO_API_BASE

    def set_api_key(self, api_key):
        self.api_key = api_key

    def set_provider(self, provider):
        self.provider = provider.lower()
        self.api_base = DOUBAO_API_BASE

    def ocr_analyze_single(self, image_path):
        logger.info(f"OCR识别截图: {image_path}")
        reader = _get_ocr_reader()
        results = reader.readtext(image_path)
        return self._parse_birth_from_ocr(results)

    def ocr_analyze_batch(self, image_paths, progress_callback=None):
        all_results = []
        total = len(image_paths)
        logger.info(f"开始OCR批量识别 {total} 张截图")
        for i, path in enumerate(image_paths):
            logger.info(f"OCR处理第 {i+1}/{total} 张截图: {path}")
            if progress_callback:
                progress_callback(i + 1, total, os.path.basename(path))
            try:
                results = self.ocr_analyze_single(path)
                for r in results:
                    r["_source"] = os.path.basename(path)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"OCR处理截图失败 {path}: {str(e)}")
        logger.info(f"OCR批量识别完成，共识别到 {len(all_results)} 条生子记录")
        return all_results

    @staticmethod
    def _fix_ocr_text(text):
        fixes = {
            '予': '子', '于': '子', '孑': '子',
            '名日': '名曰', '名白': '名曰', '名目': '名曰',
            '《': '', '》': '', '(': '', ')': '', '【': '', '】': '',
            '～': '', '~': '',
            '婢': '娀', '俾': '娀',
            '姜': '姜', '妾': '妾',
            '姬': '姬', '姖': '姬',
            '姚': '姚', '娆': '姚',
            '妘': '妘', '芸': '妘', '云': '妘',
            '姒': '姒', '似': '姒',
            '姞': '姞', '吉': '姞',
            '姑': '姑', '估': '姑',
            '隗': '隗', '槐': '隗',
            '妫': '妫', '为': '妫',
            '风': '风', '凤': '风',
            '有': '有', '友': '有',
            '皇': '皇', '黄': '皇',
            '极': '极', '吉': '极',
            '居': '居', '据': '居',
            '离': '离', '黎': '离',
            '俞': '俞', '逾': '俞',
            '寅': '寅', '演': '寅',
            '蒙': '蒙', '萌': '蒙',
            '防': '防', '房': '防',
            '收': '收', '守': '收',
            '句': '句', '勾': '句',
            '厌': '厌', '雁': '厌',
            '英': '英', '婴': '英',
            '灵': '灵', '玲': '灵',
            '非': '非', '飞': '非',
            '若': '若', '婼': '若',
            '太': '太', '泰': '太',
            '女句': '姌',
            '名日': '名曰', '名白': '名曰', '名目': '名曰',
            '《': '', '》': '', '(': '', ')': '', '【': '', '】': '',
            '～': '', '~': '',
        }
        for old, new in fixes.items():
            text = text.replace(old, new)
        return text

    def _parse_birth_from_ocr(self, ocr_results):
        items = []
        for bbox, text, conf in ocr_results:
            if conf > 0.2:
                items.append({
                    'y': bbox[0][1],
                    'x': bbox[0][0],
                    'text': text.strip(),
                })

        if not items:
            return []

        items.sort(key=lambda x: (x['y'], x['x']))

        GROUPS = []
        current_group = [items[0]]
        for item in items[1:]:
            if abs(item['y'] - current_group[-1]['y']) <= 25:
                current_group.append(item)
            else:
                GROUPS.append(current_group)
                current_group = [item]
        GROUPS.append(current_group)

        lines = []
        for group in GROUPS:
            sorted_group = sorted(group, key=lambda x: x['x'])
            joined = ''.join(item['text'] for item in sorted_group)
            joined = self._fix_ocr_text(joined)
            avg_y = sum(item['y'] for item in group) / len(group)
            lines.append((avg_y, joined))

        lines.sort(key=lambda x: x[0])

        EVENT_GAP = 80

        events = []
        current_event_lines = [lines[0]]
        for i in range(1, len(lines)):
            if lines[i][0] - current_event_lines[-1][0] <= EVENT_GAP:
                current_event_lines.append(lines[i])
            else:
                events.append(current_event_lines)
                current_event_lines = [lines[i]]
        events.append(current_event_lines)

        records = []
        seen = set()

        for event in events:
            father = ""
            child = ""
            year = ""

            for _, t in event:
                child_m = re.search(r'名曰\s*(.+)', t)
                if child_m:
                    child = child_m.group(1).strip()
                    child = re.sub(r'[。.]\s*天智?\d+.*$', '', child)
                    child = re.sub(r'天智?\d+.*$', '', child)
                    child = child.rstrip('。.').strip()

                father_m = re.search(r'(.{1,8})新得一子', t)
                if father_m:
                    father = father_m.group(1).strip()

                year_m = re.search(r'天智(\d+)', t)
                if year_m:
                    year = year_m.group(1)

            if child:
                child = child.strip()
                father = father.strip()
                if len(child) > 6:
                    child = child[:6]
                key = (child, father)
                if key in seen:
                    continue
                seen.add(key)

                year_str = f"天智{year}" if year else ""
                records.append({
                    "year": year_str,
                    "father": father,
                    "mother": "",
                    "child": child,
                    "gender": "男",
                })

        logger.info(f"OCR解析到 {len(records)} 条生子记录: {[(r['father'], r['child'], r['year']) for r in records]}")
        return records

    def _encode_image(self, image_path):
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _get_content_type(self, image_path):
        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        return mime_map.get(ext, "image/png")

    def _call_doubao_api(self, image_data_uri):
        if requests is None:
            raise RuntimeError(REQUESTS_MISSING_MSG)
        if not self.api_key:
            raise ValueError("API Key未设置，请在设置中配置豆包API Key")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": image_data_uri,
                        },
                        {
                            "type": "input_text",
                            "text": DETECTION_PROMPT,
                        },
                    ],
                }
            ],
        }

        url = f"{self.api_base}/responses"
        logger.info(f"调用豆包API: 模型={self.model}")

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()

            logger.debug(f"豆包API返回完整数据: {json.dumps(data, ensure_ascii=False)[:500]}")

            output_text = ""
            if "output" in data:
                output_list = data["output"]
                if isinstance(output_list, list) and len(output_list) > 0:
                    for item in output_list:
                        if isinstance(item, dict):
                            content = item.get("content", "")
                            if isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "output_text":
                                        output_text += c.get("text", "")
                            elif isinstance(content, str):
                                output_text = content
            elif "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0].get("message", {}).get("content", "")
                output_text = content

            if not output_text:
                raise ValueError("豆包API返回结果中未找到输出文本")

            logger.info(f"豆包API调用成功，返回内容长度: {len(output_text)}字符")
            return output_text
        except requests.exceptions.Timeout:
            logger.error("豆包API请求超时")
            raise RuntimeError("豆包API请求超时，请检查网络连接")
        except requests.exceptions.RequestException as e:
            logger.error(f"豆包API请求失败: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"豆包API返回状态码: {e.response.status_code}")
                logger.error(f"豆包API返回内容: {e.response.text[:500]}")
            raise RuntimeError(f"豆包API请求失败: {str(e)}")

    def analyze_single(self, image_path):
        logger.info(f"分析截图: {image_path}")
        if self.provider != "doubao":
            # ★ 代码改进 A14：DeepSeek 对话模型不支持图像输入（实测必报错），
            #   与其让使用者看 API 报错，不如一开始就说清。
            raise RuntimeError(
                "图像识别需要视觉模型：请改用豆包（doubao）并在设置里配置豆包 API Key。"
                "（DeepSeek 不支持图像输入）")
        base64_img = self._encode_image(image_path)
        content_type = self._get_content_type(image_path)
        data_uri = f"data:{content_type};base64,{base64_img}"

        response_text = self._call_doubao_api(data_uri)

        results = self._parse_response(response_text)
        logger.info(f"从截图识别到 {len(results)} 条出生记录")
        return results

    def analyze_batch(self, image_paths, progress_callback=None):
        all_results = []
        total = len(image_paths)
        logger.info(f"开始批量分析 {total} 张截图")

        for i, path in enumerate(image_paths):
            logger.info(f"处理第 {i+1}/{total} 张截图: {path}")
            if progress_callback:
                progress_callback(i + 1, total, os.path.basename(path))
            try:
                results = self.analyze_single(path)
                for r in results:
                    r["_source"] = os.path.basename(path)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"处理截图失败 {path}: {str(e)}")

        logger.info(f"批量分析完成，共识别到 {len(all_results)} 条出生记录")
        return all_results

    def _parse_response(self, text):
        text = text.strip()

        if text.startswith("```"):
            lines = text.split("\n")
            start = 0
            end = len(lines)
            for i, line in enumerate(lines):
                if line.strip().startswith("```") and start == 0:
                    start = i + 1
                elif line.strip().startswith("```"):
                    end = i
            text = "\n".join(lines[start:end]).strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for key in ["data", "results", "records", "births", "children"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return [data]
        except json.JSONDecodeError:
            pass

        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        logger.warning(f"无法解析API返回内容，前200字符: {text[:200]}")
        return []

    def _similarity(self, s1, s2):
        if not s1 or not s2:
            return 0.0
        s1, s2 = s1.strip(), s2.strip()
        max_len = max(len(s1), len(s2))
        if max_len == 0:
            return 1.0
        
        matches = 0
        for i in range(min(len(s1), len(s2))):
            if s1[i] == s2[i]:
                matches += 1
        
        return matches / max_len

    def _find_similar_name(self, name, known_names, threshold=0.5):
        best_match = None
        best_score = threshold

        name_given = name[1:] if len(name) >= 2 else name
        name_last2 = name[-2:] if len(name) >= 2 else name

        for known in known_names:
            known_given = known[1:] if len(known) >= 2 else known
            known_last2 = known[-2:] if len(known) >= 2 else known

            if len(name) >= 3 and len(known) >= 3:
                if name_given == known_given:
                    score = 0.9
                    if score > best_score:
                        best_score = score
                        best_match = known

            if len(name) >= 2 and len(known) >= 2:
                if name[-2:] == known[-2:]:
                    score = 0.85
                    if score > best_score:
                        best_score = score
                        best_match = known

            if len(name) >= 1 and len(known) >= 1:
                if name[-1:] == known[-1:]:
                    score = 0.6
                    if score > best_score:
                        best_score = score
                        best_match = known

            score = self._similarity(name, known)
            if score > best_score:
                best_score = score
                best_match = known

        return best_match, best_score

    def match_against_tree(self, results, known_names):
        matched_results = []

        for item in results:
            father = item.get("father", "").strip()
            child = item.get("child", "").strip()
            year = item.get("year", "").strip()
            mother = item.get("mother", "").strip()
            gender = item.get("gender", "男")

            father_exists = father in known_names
            mother_exists = mother in known_names if mother else None
            
            suggested_father = None
            confidence = 1.0
            
            if not father_exists and father:
                suggested_father, confidence = self._find_similar_name(father, known_names)
                if suggested_father:
                    father_exists = True

            matched_results.append({
                "year": year,
                "father": father,
                "mother": mother,
                "child": child,
                "gender": gender,
                "father_exists": father_exists,
                "mother_exists": mother_exists,
                "suggested_father": suggested_father,
                "confidence": confidence,
                "can_add": father_exists,
                "_source": item.get("_source", ""),
            })

        return matched_results


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            # utf-8-sig：兼容记事本等编辑器保存时带 BOM 的配置文件
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取配置文件失败: {str(e)}")
    return {"deepseek_api_key": "", "deepseek_model": DEFAULT_MODEL}


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {str(e)}")
        return False
