    for _ in range(settings.MAX_TOOL_ITERATIONS):
        if _ctx_should_compact(messages):
            try:
                _new_msgs, _mid_summary, _did = await asyncio.to_thread(
                    _ctx_compact, messages, provider, model
                )
                if _did:
                    _saved = _ctx_estimate(messages) - _ctx_estimate(_new_msgs)
                    log_event("context_compacted_midturn", saved_tokens=_saved)
                    messages = _new_msgs
                    if on_event:
                        try:
                            await on_event({
                                "type": "context_compacted",
                                "saved_tokens": _saved,
                                "summary": _mid_summary or {},
                                "usage": _ctx_usage(messages),
                            })
                        except Exception:
                            pass
            except Exception:
                pass

        # Real-time streaming logic
        queue = asyncio.Queue()
        
        def _stream_chat():
            try:
                gen = provider.chat(messages=messages, tools=tools or None, model=model, stream=True)
                for chunk in gen:
                    queue.put_nowait(chunk)
            except Exception as e:
                queue.put_nowait(e)
            finally:
                queue.put_nowait(None)
                
        asyncio.create_task(asyncio.to_thread(_stream_chat))
        
        full_content = ""
        full_tool_calls = []
        
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            if isinstance(chunk, Exception):
                raise chunk
                
            text = chunk.get("content") or ""
            if text:
                full_content += text
                if on_event:
                    await on_event({"type": "stream", "text": text})
                    
            if chunk.get("tool_calls"):
                full_tool_calls.extend(chunk["tool_calls"])
                
        msg = {"content": full_content, "tool_calls": full_tool_calls}
        calls = msg.get("tool_calls") or []

        if not calls:
            reply = (msg.get("content") or "").strip()
            # ... (Keep the rest of the existing logic starting from 'if _looks_like_text_tool_call...')