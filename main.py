from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import yaml
import subprocess
import logging
from datetime import datetime
import os

# === Настройка логгирования ===
log_file = "alert_executor.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Alert Executor API",
    description="API для выполнения команд при получении алертов из Alertmanager / Grafana.",
    version="1.0"
)

# === Модели для валидации JSON-запросов ===
class Alert(BaseModel):
    status: str
    labels: Dict[str, str]
    annotations: Dict[str, str]
    generatorURL: str


class AlertRequest(BaseModel):
    receiver: str
    status: str
    alerts: List[Alert]
    groupLabels: Optional[Dict[str, str]] = None
    commonLabels: Optional[Dict[str, str]] = None
    commonAnnotations: Optional[Dict[str, str]] = None


# === Обработчик ошибок валидации ===
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: Exception):
    logger.error(f"Ошибка валидации запроса: {exc}")
    return {
        "status": "error",
        "detail": exc.errors(),
        "body": exc.body
    }


# === Роуты ===
@app.post("/alert")
def handle_alert(data: AlertRequest):
    """
    Принимает POST-запрос с данными алерта.
    Обрабатывает только алерты со статусом 'firing'.
    """
    try:
        logger.info("Получен новый запрос с алертами")

        results = []

        for alert in data.alerts:
            alert_status = alert.status.lower()
            alert_name = alert.labels.get("alertname", "unknown")
            generator_url = alert.generatorURL

            logger.info(f"Обработка алерта '{alert_name}' со статусом '{alert_status}'")

            # Фильтр: обрабатываем только firing алерты
            if alert_status != "firing":
                logger.info(f"Алерт '{alert_name}' со статусом '{alert_status}' игнорируется.")
                continue

            # Извлечение alert_id из generatorURL
            parts = generator_url.split('/')
            try:
                grafana_index = parts.index('grafana')
                alert_id = parts[grafana_index + 1]
                logger.info(f"Извлечён alert_id: {alert_id}")
            except (ValueError, IndexError) as e:
                logger.error(f"Не удалось найти alert_id в generatorURL: {e}")
                results.append({
                    "alert": alert_name,
                    "error": f"Invalid generatorURL format: {generator_url}"
                })
                continue

            # Загрузка конфигурации и выполнение команд
            config_path = "alerts_config.yaml"
            if not os.path.exists(config_path):
                logger.error(f"Файл конфигурации '{config_path}' не найден.")
                results.append({
                    "alert": alert_name,
                    "error": "Configuration file not found"
                })
                continue

            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

            command_to_run = None
            for item in config.get("alert", []):
                if alert_id in item:
                    command_to_run = item[alert_id].get("command")
                    break

            if not command_to_run:
                logger.warning(f"Команда для alert_id '{alert_id}' не найдена.")
                results.append({
                    "alert": alert_name,
                    "alert_id": alert_id,
                    "warning": "No command found for this alert_id"
                })
                continue

            logger.info(f"Найдена команда(ы) для alert_id '{alert_id}': {command_to_run}")

            # Приведение к списку
            if not isinstance(command_to_run, list):
                command_to_run = [command_to_run]

            # Выполнение команд
            for cmd in command_to_run:
                logger.info(f"Выполняется команда: {cmd}")
                try:
                    result = subprocess.run(
                        cmd,
                        shell=True,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=60
                    )
                    stdout = result.stdout.strip()
                    stderr = result.stderr.strip()

                    logger.info(f"STDOUT: {stdout}")
                    if stderr:
                        logger.warning(f"STDERR: {stderr}")

                    results.append({
                        "alert": alert_name,
                        "alert_id": alert_id,
                        "command": cmd,
                        "status": "success",
                        "stdout": stdout,
                        "stderr": stderr
                    })

                except subprocess.CalledProcessError as e:
                    logger.error(f"Ошибка при выполнении команды: {e}")
                    logger.error(f"STDOUT: {e.stdout.strip() if e.stdout else '(пусто)'}")
                    logger.error(f"STDERR: {e.stderr.strip() if e.stderr else '(пусто)'}")
                    results.append({
                        "alert": alert_name,
                        "alert_id": alert_id,
                        "command": cmd,
                        "status": "failed",
                        "stdout": e.stdout.strip() if e.stdout else "",
                        "stderr": e.stderr.strip() if e.stderr else ""
                    })
                except subprocess.TimeoutExpired as e:
                    logger.error(f"Таймаут выполнения команды: {cmd}")
                    results.append({
                        "alert": alert_name,
                        "alert_id": alert_id,
                        "command": cmd,
                        "status": "timeout",
                        "stdout": "",
                        "stderr": "Command timed out"
                    })

        return {"results": results}

    except Exception as e:
        logger.exception(f"Произошла ошибка при обработке запроса: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# === Точка входа ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=9999, reload=True)
