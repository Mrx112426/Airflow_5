import json
import requests
import pandas as pd
from datetime import timedelta
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.hooks.postgres_hook import PostgresHook
from airflow.utils.dates import days_ago

# Константы
NASA_API_KEY = Variable.get("NASA_API_KEY")
URL = f"https://api.nasa.gov/planetary/apod?api_key={NASA_API_KEY}&count=5"
LOCAL_FILE_PATH = "/opt/airflow/data/nasa_data.json"
PROCESSED_CSV_PATH = "/opt/airflow/data/nasa_data.csv"


def download_data():
    """Загружает данные из NASA APOD API"""
    response = requests.get(URL)
    if response.status_code == 200:
        with open(LOCAL_FILE_PATH, "w") as file:
            json.dump(response.json(), file)
    else:
        raise Exception(f"Ошибка при запросе NASA API: {response.status_code}")


def process_data():
    """Обрабатывает и нормализует данные"""
    with open(LOCAL_FILE_PATH, "r") as file:
        data = json.load(file)

    df = pd.DataFrame(data)
    df.to_csv(PROCESSED_CSV_PATH, index=False)


def export_to_postgres():
    """Сохраняет данные в PostgreSQL"""
    df = pd.read_csv(PROCESSED_CSV_PATH)
    hook = PostgresHook(postgres_conn_id=" ")
    conn = hook.get_conn()
    cursor = conn.cursor()

    for _, row in df.iterrows():
        cursor.execute(
            """
            INSERT INTO nasa_images (date, title, explanation, url, media_type)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (row["date"], row["title"], row["explanation"], row["url"], row["media_type"])
        )

    conn.commit()
    cursor.close()
    conn.close()


# Параметры DAG
default_args = {
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "start_date": days_ago(1),
}

with DAG(
        "nasa_apod_pipeline",
        default_args=default_args,
        description="NASA APOD data pipeline",
        schedule_interval="0 12 * * *",  # Запуск каждый день в 12 UTC
        catchup=False,
        tags=["nasa"],
) as dag:
    download_task = PythonOperator(
        task_id="download_data",
        python_callable=download_data
    )

    process_task = PythonOperator(
        task_id="process_data",
        python_callable=process_data
    )

    create_table_task = PostgresOperator(
        task_id="create_table",
        postgres_conn_id="postgres_nasa",
        sql="""
        CREATE TABLE IF NOT EXISTS nasa_images (
            id SERIAL PRIMARY KEY,
            date TEXT,
            title TEXT,
            explanation TEXT,
            url TEXT,
            media_type TEXT
        );
        """,
    )

    export_task = PythonOperator(
        task_id="export_to_postgres",
        python_callable=export_to_postgres
    )

    # Определяем порядок выполнения
    [download_task, create_table_task] >> process_task >> export_task
