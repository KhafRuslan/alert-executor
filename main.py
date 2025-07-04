from flask import Flask, request
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
####################################


app = Flask(__name__)
@app.route('/', methods=['POST'])
def handle_post():
    data = request.get_json()

    try:
        generator_url = data['alerts'][0]['generatorURL']
        parts = generator_url.split('/')

        try:
            grafana_index = parts.index('grafana')
            alert_id = parts[grafana_index + 1]
            logger.info(f"Извлечён alert_id: {alert_id}")
        except (ValueError, IndexError) as e:
            logger.error(f"Не удалось найти alert_id в generatorURL: {e}")
            return "Invalid alert format", 400

        with open("alerts_config.yaml", "r") as f:
            config = yaml.safe_load(f)

        # Поиск нужного alert_id
        command_to_run = None
        for item in config["alert"]:
            if alert_id in item:
                command_to_run = item[alert_id].get("command")
                break

        if not command_to_run:
            logger.warning(f"Команда для alert_id '{alert_id}' не найдена.")
        else:
            logger.info(f"Найдена команда(ы) для alert_id '{alert_id}': {command_to_run}")

            # Если команда одна — оборачиваем в список для унификации обработки
            if not isinstance(command_to_run, list):
                command_to_run = [command_to_run]

            # Выполнение команд поочерёдно
            for cmd in command_to_run:
                logger.info(f"Выполняется команда: {cmd}")
                try:
                    result = subprocess.run(
                        cmd,
                        shell=True,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )

                    logger.info(f"STDOUT: {result.stdout.strip()}")
                    if result.stderr.strip():
                        logger.warning(f"STDERR: {result.stderr.strip()}")

                    logger.info(f"Команда успешно выполнена: {cmd}")

                except subprocess.CalledProcessError as e:
                    logger.error(f"Ошибка при выполнении команды: {e}")
                    logger.error(f"STDOUT: {e.stdout.strip() if e.stdout else '(пусто)'}")
                    logger.error(f"STDERR: {e.stderr.strip() if e.stderr else '(пусто)'}")

    except Exception as e:
        logger.exception(f"Произошла ошибка при обработке запроса: {e}")
        return "Internal Server Error", 500

    return "Command executed successfully", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9999)
