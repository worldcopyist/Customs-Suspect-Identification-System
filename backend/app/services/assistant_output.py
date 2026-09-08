"""Deterministic business facts and strictly shaped, evidence-bound model output.

This validates structure, not truth of free-form knowledge prose. Detection
facts and manual links are never copied back from model-generated prose.
"""
import json
import re
from datetime import UTC
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.services.security import ApiError

PROMPT_VERSION = "customs-text-v3"
FORBIDDEN_OUTPUT = ("已确认嫌疑人", "犯罪概率", "确认该人为嫌疑人", "自动确认身份", "已确认犯罪", "应当逮捕")
CHECKS = {
    "VERIFY_SOURCE": "人工核对原始来源、采集时间和画面质量。",
    "REVIEW_CANDIDATES": "由有权限人员复核候选检测框；检测框不等于身份。",
    "CHECK_MANUAL_LINKS": "核对人工关联依据，不能将关联误写为模型识别身份。",
    "CONFIRM_SCOPE": "确认材料适用范围和缺失信息，不据此形成执法结论。",
}
CheckCode = Literal["VERIFY_SOURCE", "REVIEW_CANDIDATES", "CHECK_MANUAL_LINKS", "CONFIRM_SCOPE"]

class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class Check(Output):
    code: CheckCode
    citations: list[str] = Field(min_length=1, max_length=10)

class DetectionDraft(Output):
    pending_checks: list[Check] = Field(min_length=1, max_length=8)

class KnowledgePoint(Output):
    text: str = Field(min_length=1, max_length=1500)
    citations: list[str] = Field(min_length=1, max_length=4)

class KnowledgeDraft(Output):
    points: list[KnowledgePoint] = Field(min_length=1, max_length=8)
    scope_note: str = Field(min_length=1, max_length=1500)

def output_instruction(mode):
    if mode in {"SUMMARY", "REPORT"}:
        return ('本次模式为'+mode+'。只返回严格 JSON，不要 Markdown 围栏：'
                '{"pending_checks":[{"code":"VERIFY_SOURCE","citations":["D1"]}]}。'
                'code 只能从 VERIFY_SOURCE、REVIEW_CANDIDATES、CHECK_MANUAL_LINKS、CONFIRM_SCOPE 中选择，'
                'citations 只能使用本次证据标签。请按问题与证据选择必要的人工核对事项。'
                '数量、日期、复核和关联事实由后端生成，你不能输出或改写这些事实，不允许其他字段。')
    if mode == "KNOWLEDGE":
        return ('本次模式为 KNOWLEDGE。只返回严格 JSON，不要 Markdown 围栏：'
                '{"points":[{"text":"有依据的回答要点","citations":["K1"]}],'
                '"scope_note":"资料不足或适用范围说明"}。每个要点必须绑定本次证据，'
                '没有证据支持的断言不得输出，不允许其他字段、外部链接或身份/执法结论。')
    return '本次模式为 GENERAL，返回简明文本，明确不确定性；不要输出检测报告。'

def detection_snapshot(item, label):
    timestamp=item.finished_at or item.created_at
    snapshot={"label":label,"record_id":item.id,"version":item.version,"source":item.source,
              "time_utc":timestamp.replace(tzinfo=UTC).isoformat() if timestamp else None,
              "state":item.state,"model":item.model_id,"model_hash":(item.model_sha256 or '')[:12],
              "threshold":item.config_snapshot.get("threshold"),"debug_threshold":item.config_snapshot.get("debug_threshold","未标记"),"box_count":len(item.boxes),
              "confidences":[round(box.confidence,4) for box in sorted(item.boxes,key=lambda x:x.box_index)],
              "review_status":item.review_status,
              "manual_links":[{"box":box.box_index+1,"person_code":box.person_link.get("person_code_snapshot"),"basis":"人工关联"}
                              for box in sorted(item.boxes,key=lambda x:x.box_index) if box.person_link]}
    encoded=json.dumps(snapshot,ensure_ascii=False,separators=(',',':'))
    if len(encoded)>800:
        raise ApiError(422,"CONTEXT_TOO_LARGE","单条检测事实超过800字符安全预算，不能截断复核或关联限定后外发")
    return snapshot,encoded

def safe_text(value):
    # Keep database values literal inside the server-owned Markdown layout.
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])',r'\\\1',str(value if value is not None else '未知').replace('\n',' ').replace('\r',' '))

def validate_citations(labels, allowed):
    if len(set(labels))!=len(labels) or not set(labels).issubset(allowed):
        raise ApiError(502,"OUTPUT_VALIDATION_FAILED","回答包含未知或重复证据标签")

def render_business_answer(text, request):
    if request.mode == "GENERAL":return text
    allowed={x['label'] for x in request.source_refs}
    try:
        if request.mode == "KNOWLEDGE":
            data=KnowledgeDraft.model_validate_json(text)
            for point in data.points:validate_citations(point.citations,allowed)
            if re.search(r'https?://|www\.',text,re.I):raise ValueError('external link')
            points=['- '+safe_text(point.text)+' '+''.join('['+label+']' for label in point.citations) for point in data.points]
            return '## 回答要点\n'+ '\n'.join(points)+'\n\n## 资料范围与不足\n'+safe_text(data.scope_note)+'\n\n资料解读由AI生成，引用关联不能证明每一句话正确，请逐项核对原文。'
        data=DetectionDraft.model_validate_json(text)
        for check in data.pending_checks:validate_citations(check.citations,allowed)
    except (ValidationError,ValueError,TypeError) as exc:
        raise ApiError(502,"OUTPUT_VALIDATION_FAILED","业务回答结构不合法；未作为正式答案展示，也不会自动再次调用模型") from exc
    snapshots=request.outbound_payload.get('fact_snapshots')
    if not snapshots or {x['label'] for x in snapshots}!=allowed:
        raise ApiError(502,"OUTPUT_VALIDATION_FAILED","缺少完整冻结事实，不能生成报告")
    heading='# 业务检测报告草稿' if request.mode=='REPORT' else '# 业务检测事件摘要'
    lines=[heading,'','## 基本情况',f'本次明确选择 {len(snapshots)} 条记录；以下事实由后端冻结数据生成，不由模型改写。','', '## 检测结果']
    for row in snapshots:
        lines.append(f"- [{row['label']}] 记录 {safe_text(row['record_id'])}；来源 {safe_text(row['source'])}；时间（UTC）{safe_text(row['time_utc'])}；状态 {safe_text(row['state'])}；候选框 {row['box_count']} 个；阈值 {safe_text(row['threshold'])}；置信度 {safe_text(row['confidences'])}；模型 {safe_text(row['model'])} / {safe_text(row['model_hash'])}。")
    lines+=['','## 人工复核']+[f"- [{row['label']}] {safe_text(row['review_status'])}（数据库复核状态）" for row in snapshots]
    lines+=['','## 人工关联']
    for row in snapshots:
        links='；'.join(f"第 {link['box']} 框 → 虚拟人员编号 {safe_text(link['person_code'])}（人工关联）" for link in row['manual_links']) or '尚无人工关联'
        lines.append(f"- [{row['label']}] {links}。关联不是模型身份判断。")
    lines+=['','## 限制与待确认事项','仅用于企业演示；框数不是去重人数，未检出也不能证明不存在目标。','以下核对事项由AI从固定清单选择，并非事实结论：']
    for check in data.pending_checks:lines.append('- '+CHECKS[check.code]+' '+''.join('['+x+']' for x in check.citations))
    lines+=['','## 来源清单']+[f"- [{row['label']}] 检测记录 {safe_text(row['record_id'])}，版本 {row['version']}" for row in snapshots]
    return '\n'.join(lines)
