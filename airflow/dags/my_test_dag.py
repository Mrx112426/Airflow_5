from datetime import timedelta
# The DAG object; we'll need this to instantiate a DAG
from airflow.models.dag import DAG
# Operators; we need this to operate!
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

def print_hello():
    print('Hello Airflow in Python!')
with DAG(
    "my_test_dag",
    # [START default_args]
    # These args will get passed on to each operator
    # You can override them on a per-task basis during operator initialization
    default_args={
        "depends_on_past": False,
        "email": ["airflow@example.com"],
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 1,
        "retry_delay": timedelta(minutes=5),

    },
    # [END default_args]
    description="My test Dag",
    schedule=None,
    start_date=days_ago(1),
    tags=["test"],
) as dag:
        bash = BashOperator(
            task_id="bash",
            bash_command="echo Hello Airflow in bash!"
        )
        python = PythonOperator(
            task_id='python',
            python_callable=print_hello
        )
###Работу выполнил Мазориев Умар 4217
[bash,python]