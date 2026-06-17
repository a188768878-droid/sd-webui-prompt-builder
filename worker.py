import requests
import time
import json
import traceback
import random
import base64
import os
import ctypes
import re
import sys
from datetime import datetime

# ==========================================
# ⚙️ 核心配置区 (基础环境变量设定)
# ==========================================
WORKER_NODE_NAME = "Node_Default"

SERVER_BASE_URL = "https://your-api-domain.com/api/v1/worker"
WORKER_SECRET = "your_secure_secret_token"
COMFYUI_URL = "http://127.0.0.1:8188"
REQUEST_TIMEOUT = 15

# ==========================================
# 🧩 ComfyUI 节点 ID 映射区 (对应 workflow_api.json)
# ==========================================
NODE_CKPT = "7"
NODE_PROMPT = "152"
NODE_NEG_PROMPT = "153"
NODE_STYLE_LORA = "129"
NODE_OTHER_LORA = "150"
NODE_CHAR_LORA_STACK = "108"
NODE_LATENT = "9"
NODE_SAVE_IMAGE = "13"
NODE_LOAD_IMAGE = "132"
NODE_IMAGE_SCALE = "148"
NODE_CONTROLNET_APPLY = "147"
NODE_KSAMPLER_1 = "8"
NODE_HAND_DETAILER = "26"
NODE_FOOT_DETAILER = "37"

SEED_NODES = ["8", "11", "26", "28", "37", "152", "153"]


def get_comfyui_workflow():
    """读取本地的 ComfyUI API 格式工作流图纸"""
    try:
        with open("workflow_api.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise Exception("Missing workflow_api.json file. Please check path configuration.")
    except json.JSONDecodeError:
        raise Exception("Failed to parse workflow_api.json due to invalid format.")


def disable_quick_edit():
    """禁用 CMD 快速编辑模式，防止鼠标点击终端导致程序挂起死锁"""
    if os.name == 'nt':
        try:
            kernel32 = ctypes.windll.kernel32
            STD_INPUT_HANDLE = -10
            ENABLE_QUICK_EDIT_MODE = 0x0040
            handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
            mode = ctypes.c_uint32()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            new_mode = mode.value & ~ENABLE_QUICK_EDIT_MODE
            kernel32.SetConsoleMode(handle, new_mode)
            print("[+] Windows QuickEdit mode disabled successfully.")
        except Exception as e:
            print(f"[!] Failed to disable QuickEdit mode: {e}")


def check_comfyui_health():
    """检查 ComfyUI 引擎是否存活"""
    try:
        requests.get(f"{COMFYUI_URL}/system_stats", timeout=3)
    except requests.exceptions.RequestException:
        print("\n[!] ComfyUI backend server is unavailable.")
        sys.exit(1)


def upload_base64_to_comfyui(b64_data, filename_prefix):
    """将后端的 Base64 图片还原并上传给 ComfyUI 作为输入图"""
    if "," in b64_data:
        b64_data = b64_data.split(",")[1]
    img_bytes = base64.b64decode(b64_data)
    filename = f"{filename_prefix}_{int(time.time())}.png"
    files = {"image": (filename, img_bytes, "image/png")}
    res = requests.post(f"{COMFYUI_URL}/upload/image", files=files, timeout=REQUEST_TIMEOUT)
    if res.status_code != 200:
        raise Exception(f"ComfyUI rejected image upload, Status Code: {res.status_code}")
    return res.json().get("name")


def bypass_node(workflow, node_id_to_bypass, output_mapping):
    """
    网络拓扑旁路（剪枝缝合术）
    功能：删除多余节点，并将其原本的输入线“嫁接”到其下游节点。
    """
    if node_id_to_bypass not in workflow:
        return
    bypassed_node = workflow[node_id_to_bypass]
    inputs = bypassed_node.get("inputs", {})

    for nid, ndata in workflow.items():
        if "inputs" in ndata:
            for key, val in list(ndata["inputs"].items()):
                if isinstance(val, list) and val[0] == node_id_to_bypass:
                    out_idx = val[1]
                    if out_idx in output_mapping:
                        input_name = output_mapping[out_idx]
                        if input_name in inputs:
                            ndata["inputs"][key] = inputs[input_name]
    del workflow[node_id_to_bypass]


def run_worker():
    print("[+] AI Queue Worker initialized. Listening for tasks...\n")
    headers = {"Worker-Secret": WORKER_SECRET}

    while True:
        try:
            check_comfyui_health()
            print("\r[*] Fetching tasks from cloud server...", end="", flush=True)
            response = requests.get(f"{SERVER_BASE_URL}/tasks/pull/{WORKER_NODE_NAME}", headers=headers,
                                    timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                time.sleep(5)
                continue
            res_json = response.json()
            if res_json.get("status") != 200:
                time.sleep(5)
                continue
            task = res_json.get("data")
            if not task:
                time.sleep(3)
                continue
        except Exception:
            time.sleep(5)
            continue

        print()
        task_no = task.get("taskNo")
        task_start_time = time.time()

        try:
            prompt_text = task.get("prompt", "")
            negative_prompt = task.get("negativePrompt", "")
            params = task.get("generateParams", {})
            task_type = params.get("task_type", "text2img")
            user_id = task.get("userId", -1)

            formatted_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print(f"==================================================")
            print(f"[+] Task received | Type: [{task_type.upper()}] | ID: {task_no} | Time: {formatted_time}")

            workflow = get_comfyui_workflow()

            # ==========================================================
            # 1. 基础参数与提示词载入
            # ==========================================================
            workflow[NODE_PROMPT]["inputs"]["text"] = prompt_text
            workflow[NODE_NEG_PROMPT]["inputs"]["text"] = negative_prompt

            # ==========================================================
            # 2. 画风与人物 LoRA 处理
            # ==========================================================
            if "checkpoint" in params and params["checkpoint"]:
                workflow[NODE_CKPT]["inputs"]["ckpt_name"] = params["checkpoint"]

            style_lora = params.get("style_lora")
            if style_lora:
                if NODE_STYLE_LORA in workflow:
                    workflow[NODE_STYLE_LORA]["inputs"]["lora_name"] = style_lora
                    workflow[NODE_STYLE_LORA]["inputs"]["strength_model"] = 1.0
                    workflow[NODE_STYLE_LORA]["inputs"]["strength_clip"] = 1.0
            else:
                bypass_node(workflow, NODE_STYLE_LORA, {0: "model", 1: "clip"})

            character_loras = params.get("character_loras", [])
            for i in range(3):
                slot_idx = i + 1
                if i < len(character_loras):
                    lora_item = character_loras[i]
                    if isinstance(lora_item, dict):
                        lora_name = lora_item.get("name")
                        lora_weight = float(lora_item.get("weight", 1.0))
                    else:
                        lora_name = str(lora_item)
                        lora_weight = 1.0

                    workflow[NODE_CHAR_LORA_STACK]["inputs"][f"lora_{slot_idx}_name"] = lora_name
                    workflow[NODE_CHAR_LORA_STACK]["inputs"][f"lora_{slot_idx}_strength"] = lora_weight
                else:
                    workflow[NODE_CHAR_LORA_STACK]["inputs"][f"lora_{slot_idx}_name"] = "None"
                    workflow[NODE_CHAR_LORA_STACK]["inputs"][f"lora_{slot_idx}_strength"] = 0.0

            # ==========================================================
            # 3. 结构特征旁路检测（动态优化示例）
            # ==========================================================
            is_anime_style = bool(re.search(r'(?i)\b(anime|manga|flat color)\b', prompt_text))
            if is_anime_style:
                print("[-] Anime style optimization triggered. Adjusting topology...")

            # ==========================================================
            # 4. 动作与增强模型动态装载逻辑
            # ==========================================================
            if workflow.get(NODE_OTHER_LORA):
                for i in range(1, 11):
                    if f"lora_{i}_strength" in workflow[NODE_OTHER_LORA]["inputs"]:
                        workflow[NODE_OTHER_LORA]["inputs"][f"lora_{i}_strength"] = 0

            LORA_RULES = {
                1: (1.0, ["action_pose_a"], []),
                2: (0.9, ["clothing_style_b"], []),
                3: (0.9, ["expression_pack_c"], [])
            }

            prompt_lower = prompt_text.lower()
            max_active_slot = 0

            for slot, (strength, keywords, exceptions) in LORA_RULES.items():
                has_exception = any(re.search(rf'\b{re.escape(ex)}\b', prompt_lower) for ex in exceptions) if exceptions else False
                has_keyword = any(re.search(rf'\b{re.escape(kw)}\b', prompt_lower) for kw in keywords)

                if has_exception and has_keyword:
                    clean_prompt = prompt_lower
                    for ex in exceptions:
                        clean_prompt = re.sub(rf'\b{re.escape(ex)}\b', '', clean_prompt)
                    is_matched = any(re.search(rf'\b{re.escape(kw)}\b', clean_prompt) for kw in keywords)
                else:
                    is_matched = has_keyword and not has_exception

                if is_matched:
                    workflow[NODE_OTHER_LORA]["inputs"][f"lora_{slot}_strength"] = strength
                    max_active_slot = max(max_active_slot, slot)

            workflow[NODE_OTHER_LORA]["inputs"]["num_loras"] = max(1, max_active_slot)

            # ==========================================================
            # 5. 提示词动态同步穿透逻辑（手部/足部重绘优化示例）
            # ==========================================================
            detail_matches = re.findall(r'(?i)\b(highly detailed eyes|detailed fingers|perfect hands)\b', prompt_text)
            if detail_matches:
                detail_tags = ", ".join(list(set(detail_matches)))
                if "24" in workflow:
                    current_prompt = workflow["24"]["inputs"].get("text", "")
                    workflow["24"]["inputs"]["text"] = f"{current_prompt}, {detail_tags}"

            # ==========================================================
            # 6. 全局环境变量与基础尺寸设定
            # ==========================================================
            global_seed = random.randint(1, 1125899906842624)
            for node_id in SEED_NODES:
                if node_id in workflow:
                    workflow[node_id]["inputs"]["seed"] = int(global_seed)

            if NODE_SAVE_IMAGE in workflow:
                workflow[NODE_SAVE_IMAGE]["inputs"]["filename_prefix"] = f"output_{task_no}"

            target_width = int(params.get("width", 1344))
            target_height = int(params.get("height", 768))
            if NODE_LATENT in workflow:
                workflow[NODE_LATENT]["inputs"]["width"] = target_width
                workflow[NODE_LATENT]["inputs"]["height"] = target_height
            if NODE_IMAGE_SCALE in workflow:
                workflow[NODE_IMAGE_SCALE]["inputs"]["width"] = target_width
                workflow[NODE_IMAGE_SCALE]["inputs"]["height"] = target_height

            # ==========================================================
            #  7. 局部重绘 (Inpaint) 动态网络拓扑重构
            # ==========================================================
            if task_type == "inpaint":
                inpaint_img_b64 = params.get("inpaint_image_base64")
                inpaint_mask_b64 = params.get("inpaint_mask_base64")
                denoising_strength = params.get("denoising_strength", 0.75)

                if not inpaint_img_b64 or not inpaint_mask_b64:
                    raise Exception("Inpaint task missing image or mask data.")

                base_img_name = upload_base64_to_comfyui(inpaint_img_b64, f"inpaint_base_{task_no}")
                mask_img_name = upload_base64_to_comfyui(inpaint_mask_b64, f"inpaint_mask_{task_no}")

                workflow["901"] = {"class_type": "LoadImage", "inputs": {"image": base_img_name}}
                workflow["902"] = {"class_type": "LoadImage", "inputs": {"image": mask_img_name}}
                workflow["903"] = {"class_type": "ImageToMask", "inputs": {"image": ["902", 0], "channel": "red"}}

                workflow["904"] = {
                    "class_type": "VAEEncodeForInpaint",
                    "inputs": {
                        "pixels": ["901", 0],
                        "vae": [NODE_CKPT, 2],
                        "mask": ["903", 0],
                        "grow_mask_by": 6
                    }
                }

                if NODE_KSAMPLER_1 in workflow:
                    workflow[NODE_KSAMPLER_1]["inputs"]["latent_image"] = ["904", 0]
                    workflow[NODE_KSAMPLER_1]["inputs"]["denoise"] = denoising_strength

                if "18" in workflow:
                    workflow["18"]["inputs"]["samples"] = [NODE_KSAMPLER_1, 0]
                    workflow["18"]["inputs"]["vae"] = [NODE_CKPT, 2]

                workflow["905"] = {
                    "class_type": "ImageCompositeMasked",
                    "inputs": {
                        "destination": ["901", 0],
                        "source": ["18", 0],
                        "x": 0, "y": 0, "resize_source": False,
                        "mask": ["903", 0]
                    }
                }

                if NODE_SAVE_IMAGE in workflow:
                    workflow[NODE_SAVE_IMAGE]["inputs"]["images"] = ["905", 0]

                nodes_to_delete = ["10", "11", "26", "28", "37", "132", "133", "143", "148", "154", "155"]
                for n in nodes_to_delete:
                    if n in workflow:
                        del workflow[n]

                bypass_node(workflow, NODE_CONTROLNET_APPLY, {0: "positive", 1: "negative"})

            else:
                # ==========================================================
                #  8. 姿势与深度控制分支 (ControlNet)
                # ==========================================================
                pose_b64 = params.get("pose_image_base64")
                pose_strength = float(params.get("pose_strength", 1))

                if pose_b64 and NODE_LOAD_IMAGE in workflow and NODE_CONTROLNET_APPLY in workflow:
                    try:
                        uploaded_pose_name = upload_base64_to_comfyui(pose_b64, f"pose_{task_no}")
                        workflow[NODE_LOAD_IMAGE]["inputs"]["image"] = uploaded_pose_name
                        workflow[NODE_CONTROLNET_APPLY]["inputs"]["strength"] = pose_strength

                        use_depth = bool(re.search(r'(?i)\b(depth|perspective)\b', prompt_text))

                        if use_depth:
                            if "143" in workflow:
                                workflow["143"]["inputs"]["control_net_name"] = "controlnet_depth_model.safetensors"
                            if "155" in workflow:
                                workflow["155"]["inputs"]["images"] = ["148", 0]
                            if NODE_CONTROLNET_APPLY in workflow:
                                workflow[NODE_CONTROLNET_APPLY]["inputs"]["image"] = ["155", 0]
                            if "133" in workflow:
                                del workflow["133"]
                        else:
                            if "143" in workflow:
                                workflow["143"]["inputs"]["control_net_name"] = "controlnet_openpose_model.safetensors"
                            if NODE_CONTROLNET_APPLY in workflow:
                                workflow[NODE_CONTROLNET_APPLY]["inputs"]["image"] = ["133", 0]
                            for n in ["154", "155"]:
                                if n in workflow:
                                    del workflow[n]

                    except Exception as e:
                        raise Exception(f"Failed to process ControlNet input: {str(e)}")
                else:
                    bypass_node(workflow, NODE_CONTROLNET_APPLY, {0: "positive", 1: "negative"})
                    nodes_to_delete = [NODE_LOAD_IMAGE, "133", "143", "148", "154", "155"]
                    for n in nodes_to_delete:
                        if n in workflow:
                            del workflow[n]

            # ==========================================================
            #  9. 任务提交与队列头部插入逻辑
            # ==========================================================
            print("[*] Topology optimization completed. Submitting task to ComfyUI queue...")
            req_data = {"prompt": workflow, "front": True}
            try:
                comfy_res = requests.post(f"{COMFYUI_URL}/prompt", json=req_data, timeout=REQUEST_TIMEOUT).json()
                if "error" in comfy_res:
                    raise Exception(f"ComfyUI execution error: {comfy_res['error']}")

                prompt_id = comfy_res.get("prompt_id")
            except requests.exceptions.RequestException:
                raise Exception("Failed to connect to ComfyUI server.")

            # ==========================================================
            # 10. 轮询监控与出图捕捉 (超时保护)
            # ==========================================================
            image_filename = None
            while True:
                if time.time() - task_start_time > 600:
                    raise Exception("Rendering timeout reached (10 minutes).")
                time.sleep(10)

                try:
                    history_res = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=5).json()
                except Exception:
                    continue

                if prompt_id in history_res:
                    task_history = history_res[prompt_id]
                    status = task_history.get("status", {})
                    if status.get("status_str") == "error":
                        raise Exception("ComfyUI workflow pipeline execution failed.")

                    outputs = task_history.get("outputs", {})
                    for node_id, node_output in outputs.items():
                        if "images" in node_output:
                            image_filename = node_output["images"][0]["filename"]
                            image_subfolder = node_output["images"][0].get("subfolder", "")
                            break
                    break
                else:
                    try:
                        queue_res = requests.get(f"{COMFYUI_URL}/queue", timeout=5).json()
                        pending = queue_res.get("queue_pending", [])
                        running = queue_res.get("queue_running", [])

                        is_in_queue = False
                        for task_info in pending + running:
                            if len(task_info) > 1 and task_info[1] == prompt_id:
                                is_in_queue = True
                                break

                        if not is_in_queue:
                            final_history = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=5).json()
                            if prompt_id not in final_history:
                                raise Exception("Rendering task process terminated unexpectedly (Out of Memory).")
                    except requests.exceptions.RequestException:
                        pass

            # ==========================================================
            # 11. 结果图回传
            # ==========================================================
            if image_filename:
                try:
                    view_url = f"{COMFYUI_URL}/view?filename={image_filename}&type=output"
                    if image_subfolder:
                        view_url += f"&subfolder={image_subfolder}"

                    img_res = requests.get(view_url, timeout=REQUEST_TIMEOUT)
                    img_res.raise_for_status()
                except Exception as e:
                    raise Exception(f"Failed to fetch rendered output: {str(e)}")

                # 回送云端服务器
                files = {'file': (f"{task_no}.png", img_res.content, 'image/png')}
                try:
                    complete_res = requests.post(f"{SERVER_BASE_URL}/tasks/{task_no}/complete", headers=headers,
                                                 files=files, timeout=60)
                except Exception as e:
                    raise Exception(f"Network error during output transmission: {str(e)}")

                if complete_res.status_code == 200:
                    print(f"[+] Task {task_no} processed successfully.")
                else:
                    raise Exception(f"Server rejected task results. Code: {complete_res.status_code}")

                print(f"==================================================\n")
            else:
                raise Exception("No valid image found in pipeline outputs.")

        except Exception as e:
            error_msg = str(e)
            print(f"\n[!] Critical exception during task execution: {error_msg}")
            traceback.print_exc()

            try:
                requests.post(f"{SERVER_BASE_URL}/tasks/{task_no}/fail", headers=headers,
                              data=error_msg.encode('utf-8'), timeout=REQUEST_TIMEOUT)
            except Exception as notify_e:
                print(f"[!] Target server unreachable: {str(notify_e)}")

            if "terminated unexpectedly" in error_msg or "Failed to connect" in error_msg:
                sys.exit(1)

            time.sleep(5)


if __name__ == "__main__":
    disable_quick_edit()
    run_worker()