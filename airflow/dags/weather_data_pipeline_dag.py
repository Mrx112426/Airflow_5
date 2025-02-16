import json
from datetime import timedelta
import pandas as pd
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.hooks.postgres_hook import PostgresHook

# Константы
CITY = "Moscow"
API_KEY = Variable.get("OPENWEATHER_API_KEY")
URL = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}"
LOCAL_FILE_PATH = "/opt/airflow/data/weather_data.json"
PROCESSED_CSV_PATH = "/opt/airflow/data/processed_weather_data.csv"
PARQUET_FILE_PATH = "/opt/airflow/data/weather.parquet"


def download_data():
    """
    Функция получения данных с сервиса OpenWeatherMap
    """
    response = requests.get(URL)
    if response.status_code == 200:
        weather_data = response.json()
        with open(LOCAL_FILE_PATH, "w") as file:
            json.dump(weather_data, file)
    else:
        raise Exception(f"Error fetching data from OpenWeatherMap API: {response.status_code}. API_KEY={API_KEY}")


def process_data():
    """
    Функция очистки и преобразования загруженных данных
    """
    with open(LOCAL_FILE_PATH, "r") as file:
        weather_data_loaded = json.load(file)

    # Нормализация данных JSON
    df_main = pd.json_normalize(weather_data_loaded)
    df_weather = pd.json_normalize(weather_data_loaded, record_path=["weather"], record_prefix="weather.")

    # Объединение нормализованных данных
    df = pd.concat([df_main, df_weather], axis=1).drop(columns="weather")

    # Преобразование температур из Кельвинов в Цельсии
    for col in ["main.temp", "main.feels_like", "main.temp_min", "main.temp_max"]:
        df[col] -= 273.15

    df.to_csv(PROCESSED_CSV_PATH, index=False)


def save_data():
    """
    Функция сохранения данных в parquet-файл
    """
    processed_df = pd.read_csv(PROCESSED_CSV_PATH)
    processed_df.to_parquet(PARQUET_FILE_PATH)


def export_to_postgres():
    """
    Функция сохранения данных в Postgres БД
    """
    df = pd.read_csv(PROCESSED_CSV_PATH)
    hook = PostgresHook(postgres_conn_id="postgres_weather")
    conn = hook.get_conn()
    cursor = conn.cursor()

    for _, row in df.iterrows():
        cursor.execute(
            f"""
            INSERT INTO weather_data (
                base, visibility, dt, timezone, id, name, cod, coord_lon, coord_lat,
                main_temp, main_feels_like, main_temp_min, main_temp_max, main_pressure,
                main_humidity, main_sea_level, main_grnd_level, wind_speed, wind_deg,
                clouds_all, sys_type, sys_id, sys_country, sys_sunrise, sys_sunset,
                weather_id, weather_main, weather_description, weather_icon
            ) VALUES (
                '{row["base"]}', {row["visibility"]}, {row["dt"]}, {row["timezone"]}, {row["id"]},
                '{row["name"]}', {row["cod"]}, {row["coord.lon"]}, {row["coord.lat"]}, {row["main.temp"]},
                {row["main.feels_like"]}, {row["main.temp_min"]}, {row["main.temp_max"]}, {row["main.pressure"]},
                {row["main.humidity"]}, {row["main.sea_level"]}, {row["main.grnd_level"]}, {row["wind.speed"]},
                {row["wind.deg"]}, {row["clouds.all"]}, '{row["sys.type"]}', {row["sys.id"]},
                '{row["sys.country"]}', {row["sys.sunrise"]}, {row["sys.sunset"]}, {row["weather.id"]},
                '{row["weather.main"]}', '{row["weather.description"]}', '{row["weather.icon"]}'
            );
            """
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
        "weather_data_pipeline_dag",
        default_args=default_args,
        description="A weather data pipeline from OpenWeatherMap",
        schedule_interval="0 21 * * *",  # Запуск в полночь по MSK (UTC+3)
        catchup=False,
        tags=["weather"],
) as dag:
    download_data_task = PythonOperator(
        task_id="download_data",
        python_callable=download_data
    )

    process_data_task = PythonOperator(
        task_id="process_data",
        python_callable=process_data
    )

    save_data_task = PythonOperator(
        task_id="save_data",
        python_callable=save_data
    )

    create_weather_table = PostgresOperator(
        task_id="create_weather_table",
        postgres_conn_id="postgres_weather",
        sql="""
        CREATE TABLE IF NOT EXISTS weather_data (
            base VARCHAR(255), visibility INT, dt INT, timezone INT, id INT, name VARCHAR(255), cod INT,
            coord_lon DECIMAL(10,8), coord_lat DECIMAL(10,8), main_temp DECIMAL(10,2), main_feels_like DECIMAL(10,2),
            main_temp_min DECIMAL(10,2), main_temp_max DECIMAL(10,2), main_pressure INT, main_humidity INT,
            main_sea_level INT, main_grnd_level INT, wind_speed DECIMAL(10,2), wind_deg INT, clouds_all INT,
            sys_type VARCHAR(255), sys_id INT, sys_country VARCHAR(255), sys_sunrise INT, sys_sunset INT,
            weather_id INT, weather_main VARCHAR(255), weather_description VARCHAR(255), weather_icon VARCHAR(255)
        );
        """,
    )

    export_to_db = PythonOperator(
        task_id="export_to_db",
        python_callable=export_to_postgres
    )

    # Определение порядка выполнения задач
    [download_data_task, create_weather_table] >> process_data_task >> save_data_task >> export_to_db
