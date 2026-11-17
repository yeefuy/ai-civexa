import time

def run_multi_agent_system(user_message: str):
    system_prompt = f"""... (你的 Prompt 保持不变) ..."""
    tools = [check_doc_status, register_doc, create_official_pdf]
    
    config = types.GenerateContentConfig(
        system_instruction=system_prompt, 
        tools=tools, 
        temperature=0.2
    )

    # 【新增】自动重试与模型降级机制
    models_to_try = ["gemini-2.0-flash", "gemini-1.5-flash"] # 如果 2.0 挂了，自动试 1.5
    
    for model_name in models_to_try:
        for attempt in range(3): # 每个模型最多重试 3 次
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_message,
                    config=config,
                )
                # 如果成功，跳出循环
                break 
            except Exception as e:
                error_msg = str(e)
                if "503" in error_msg or "UNAVAILABLE" in error_msg:
                    print(f"模型 {model_name} 遇到 503 拥堵，等待 5 秒后重试... (第 {attempt+1} 次)")
                    time.sleep(5) # 等待 5 秒
                elif "404" in error_msg or "NOT_FOUND" in error_msg:
                    print(f"模型 {model_name} 不可用，尝试下一个模型...")
                    break # 404 说明模型没了，直接换下一个模型
                else:
                    raise e # 其他错误直接报错
        else:
            continue # 如果重试成功，跳出外层循环
        break # 如果生成成功，跳出外层循环

    # ... (后面提取 PDF 路径的代码保持不变) ...
