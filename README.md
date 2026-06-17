# sd-webui-prompt-builder

An open-source web utility designed for creating, managing, and optimizing Stable Diffusion prompts and LoRA configurations.

## 🚀 Features
- **Full-Stack Architecture**: Modern frontend built with Vue.js, robust backend powered by Spring Boot.
- **Queue & Worker Management**: Asynchronous task scheduling via Python background worker (`worker.py`).
- **ComfyUI Integration**: Seamlessly connect with ComfyUI API for high-performance AI generation workflows.
- **Prompt & LoRA Optimization**: Built-in logic for avoiding duplicate trigger words and auto-injecting style weights.

## 🛠️ Tech Stack
- **Frontend**: Vue 3 / Vite
- **Backend**: Java 17 / Spring Boot / MyBatis-Plus
- **AI Engine**: Python 3.10 / ComfyUI / Stable Diffusion
- **Database**: MySQL

## 📦 Quick Start
1. Configure your database settings in `application.yml`.
2. Run the Spring Boot backend server.
3. Start the local ComfyUI instance using `auto_restart.bat`.
4. Run `python worker.py` to start fetching tasks from the queue.

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.
