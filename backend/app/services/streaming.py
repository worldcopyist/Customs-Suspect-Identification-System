"""Real upstream deltas with bounded, non-durable replay. No retrying generators."""
import asyncio
import json
import time
import httpx
from app.services.security import ApiError
from app.services.assistant_output import FORBIDDEN_OUTPUT

def publish(app,id,event,data):
    stores=getattr(app.state,"assistant_events",None)
    if stores is None:stores={};app.state.assistant_events=stores
    stamp=time.monotonic()
    for key in list(stores):
        if stamp-stores[key]["updated"]>300:del stores[key]
    store=stores.setdefault(id,{"seq":0,"events":[],"bytes":0,"updated":stamp})
    store["seq"]+=1;store["updated"]=stamp
    payload=json.dumps({"request_id":id,**data},ensure_ascii=False)
    entry=(store["seq"],f"id: {id}:{store['seq']}\nevent: {event}\ndata: {payload}\n\n")
    store["events"].append(entry);store["bytes"]+=len(entry[1].encode())
    while store["bytes"]>256*1024 and store["events"]:
        store["bytes"]-=len(store["events"].pop(0)[1].encode())

async def generate_stream(config,messages,on_delta=None):
    from app.services.llm import verify_public_dns,decrypt_secret
    await asyncio.to_thread(verify_public_dns,config.base_url)
    payload={"model":config.model,"messages":messages,"stream":True,"stream_options":{"include_usage":True},"max_tokens":config.max_output_tokens}
    if config.temperature is not None:payload["temperature"]=config.temperature
    if config.provider=="DEEPSEEK":payload["thinking"]={"type":"disabled"}
    elif config.model.startswith("qwen3"):payload["enable_thinking"]=False
    text="";usage=None;finish=None;request_id=None;done=False
    try:
        async with asyncio.timeout(60),httpx.AsyncClient(timeout=httpx.Timeout(60,connect=10),follow_redirects=False,trust_env=False) as client:
            async with client.stream("POST",config.base_url+"/chat/completions",headers={"Authorization":"Bearer "+decrypt_secret(config.api_key_encrypted)},json=payload) as response:
                code=response.status_code
                if code in {401,403}:raise ApiError(502,"PROVIDER_AUTH_FAILED","云端密钥鉴权失败")
                if code==402:raise ApiError(502,"PROVIDER_QUOTA_EXCEEDED","云端余额不足")
                if code==429:raise ApiError(502,"PROVIDER_RATE_LIMITED","云端限流或配额不足")
                if code>=300:raise ApiError(502,"PROVIDER_RESPONSE_INVALID","厂商拒绝当前模型或参数，请检查配置并重新测试")
                request_id=response.headers.get("x-request-id")
                async for line in response.aiter_lines():
                    if len(line)>262144:raise ApiError(502,"PROVIDER_RESPONSE_INVALID","云端帧超出限制")
                    if not line.startswith("data:"):continue
                    data=line[5:].strip()
                    if data=="[DONE]":done=True;break
                    chunk=json.loads(data)
                    if isinstance(chunk.get("usage"),dict):usage={"input_tokens":chunk["usage"].get("prompt_tokens"),"output_tokens":chunk["usage"].get("completion_tokens")}
                    request_id=request_id or chunk.get("id")
                    choices=chunk.get("choices") or []
                    if not choices:continue
                    choice=choices[0];part=choice.get("delta",{}).get("content") or ""
                    if choice.get('delta',{}).get('tool_calls') or choice.get('delta',{}).get('function_call') or choice.get('finish_reason') in {'tool_calls','function_call'}:
                        raise ApiError(502,'PROVIDER_RESPONSE_INVALID','不接受云端工具调用')
                    if not isinstance(part,str):raise ValueError("invalid content")
                    text+=part
                    if len(text)>16000:raise ApiError(502,"OUTPUT_VALIDATION_FAILED","云端回复超出长度上限")
                    if any(x in text for x in FORBIDDEN_OUTPUT):raise ApiError(502,"OUTPUT_VALIDATION_FAILED","云端输出超出实训边界")
                    if part and on_delta:await on_delta(part)
                    finish=choice.get("finish_reason") or finish
    except (TimeoutError,httpx.TimeoutException) as exc:raise ApiError(504,"PROVIDER_TIMEOUT","云端请求超时，可能已计费；不会自动重试") from exc
    except (httpx.HTTPError,ValueError,TypeError,KeyError) as exc:raise ApiError(502,"PROVIDER_RESPONSE_INVALID","云端流中断或协议异常") from exc
    if not done or not finish or not text.strip():raise ApiError(502,"PROVIDER_RESPONSE_INVALID","云端流未正常完成，不作为有效答案")
    return {"text":text.strip(),"usage":usage,"finish_reason":finish,"request_id":request_id}
