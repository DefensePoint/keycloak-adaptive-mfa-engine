import argparse
import asyncio
import aiohttp
import time
import random
import uuid
from statistics import mean
from asyncio import Lock

import numpy as np

DEFAULT_WORKERS = 16
DEFAULT_REQUEST_INTERVAL = 5  # milliseconds
DEFAULT_DURATION = 30  # seconds
URL = "http://localhost:8095/decision"
WEBHOOK_URL = "http://localhost:8095/login_event/webhook"
TOKEN = "<your-service-account-jwt-token>"

USER_IDS = [
    "9161a2e2-47f4-4321-8455-638c1687fe88",
    "2e5637bc-233c-4a2e-98e2-22132c1923f4",
    "e8957864-dd9d-4098-bd20-b217e2bb4aef",
    "7ac3dafe-faca-4c61-ae5e-cf5e0099e29e",
    "75aa461b-78fc-468a-87a0-04a4f401b99a",
    "feccbffa-c3cc-4ff0-aac2-7f9a9538fb2c",
    "0fadf208-182b-4254-bb32-79d271789293",
    "99ee1207-fff2-4f69-ade4-858751b92f91",
    "b052516f-9125-4155-92e9-447712353b9b",
    "ecf2752a-8896-4c25-a5d5-26f0dda842c1",
    "97d90aa6-92c8-4e55-b914-448dafa620c1",
    "ddec4cdb-5fe3-4d05-a0e8-83ccfce28843",
    "b981253e-7bb8-48d5-9eb7-d73718dd38f9",
    "21eb0045-7ba1-45a3-8de4-cd23ab4693f0",
    "04a5f1c5-f7a8-4c80-bcc7-a4aa20e21a47",
    "2faec2da-85d9-4e03-91ed-c5998b31c923",
    "b2827ac4-16a5-45ee-8141-a83a856e35e7",
    "fa9c6714-71d4-4b08-b025-3b2605c10d50",
    "823335cc-eba0-48d2-bfda-1b8b2c9c45ed",
    "1bd4c091-9af5-41d9-971e-ed28b2d3541d",
    "0e14a4d3-063f-4b73-903c-2b63d151ef7f",
    "3c3b849e-bb2b-47f0-9676-f0bb44fa3e78",
    "6a0c3bb4-0ffd-4d54-806c-5307f263acfb",
    "8b81063a-a61f-4e91-a96d-8e6b98ceed47",
    "2bfeae57-91bf-4b62-89f3-bd52df3056b6",
    "e53fb27f-b1b7-4752-a16f-37c452a2d491",
    "13d3c0a1-af16-42e0-9dd9-0e1b9519e954",
    "818b130f-54c3-4c7b-becb-fe4b08c4c478",
    "c29fb26a-572f-4343-8efb-70d30bdd51cf",
    "086cf99e-88f2-490e-8c20-7cfa5bcbd6db",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
    "Mozilla/5.0 (Android 8.0.0; Mobile; rv:61.0)",
]
SYSTEM_LANGUAGES = ["en-US", "es-ES", "fr-FR", "de-DE", "zh-CN"]
SCREEN_RESOLUTIONS = ["1920x1080", "1366x768", "1440x900", "1536x864", "1280x720"]
IP_ADDRESSES = [
    "8.8.8.8",
    "8.8.4.4",
    "1.1.1.1",
    "1.0.0.1",
    "9.9.9.9",
    "208.67.222.222",
    "208.67.220.220",
    "199.85.126.10",
    "199.85.127.10",
    "77.88.8.8",
    "77.88.8.1",
    "156.154.70.1",
    "156.154.71.1",
    "94.140.14.14",
    "94.140.15.15",
    "185.228.168.9",
    "185.228.168.10",
    "80.80.80.80",
    "80.80.81.81",
    "64.6.64.6",
    "64.6.65.6",
    "8.26.56.26",
    "8.20.247.20",
    "4.2.2.1",
    "4.2.2.2",
    "205.171.3.65",
    "205.171.2.25",
    "216.146.35.35",
    "216.146.36.36",
    "45.90.28.0",
]
CLIENT_IDS = ["web", "app", "mobile"]

# Common user logins
known_data = []
for i in range(len(USER_IDS)):
    data = {
        "user_id": USER_IDS[i],
        "client_id": CLIENT_IDS[i % len(CLIENT_IDS)],
        "ip_address": IP_ADDRESSES[i],
        "user_agent": USER_AGENTS[i % len(USER_AGENTS)],
        "system_language": SYSTEM_LANGUAGES[i % len(SYSTEM_LANGUAGES)],
        "screen_resolution": SCREEN_RESOLUTIONS[i % len(SCREEN_RESOLUTIONS)],
    }
    known_data.append(data)

responses = []
latencies = []
errors = []
total_requests_sent = 0
request_id = 0
lock = Lock()


def generate_random_ip():
    return ".".join(str(random.randint(0, 255)) for _ in range(4))


async def make_request(
    session, request_id, known_data_prob=0.6, force_known_data=False, known_data_id=-1
):
    start_time = time.time()

    choice_num = random.random()
    if choice_num <= known_data_prob or force_known_data:
        if known_data_id > 0:
            data = known_data[known_data_id]
        else:
            data = random.choice(known_data)
        user_id = data["user_id"]
        client_id = data["client_id"]
        ip_address = data["ip_address"]
        user_agent = data["user_agent"]
        system_language = data["system_language"]
        screen_resolution = data["screen_resolution"]
    else:
        user_id = random.choice(USER_IDS)
        client_id = random.choice(CLIENT_IDS)
        user_agent = random.choice(USER_AGENTS)
        system_language = random.choice(SYSTEM_LANGUAGES)
        screen_resolution = random.choice(SCREEN_RESOLUTIONS)

        ip_choice_num = random.randint(1, 100)
        if ip_choice_num <= 30:
            ip_address = generate_random_ip()
        else:
            ip_address = random.choice(IP_ADDRESSES)

    params = {
        "user_id": user_id,
        "client_id": client_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "system_language": system_language,
        "screen_resolution": screen_resolution,
    }

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}

    event_id = str(uuid.uuid4())
    payload = {
        "event_id": event_id,
        "group_id": "AdaptiveAuth",
        "realm_id": "AdaptiveAuth",
        "user_id": user_id,
        "client": client_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "system_language": system_language,
        "screen_resolution": screen_resolution,
        "auth_context_hash": "jj",
    }

    try:
        async with session.post(
            URL, params=params, json=payload, headers=headers
        ) as response:
            resp_text = await response.text()
            latency = time.time() - start_time
            latencies.append(latency)
            responses.append((request_id, response.status, resp_text))
            print(
                f"Request {request_id}: Status {response.status}, Time {latency:.2f}s -> {resp_text}"
            )
    except Exception as e:
        errors.append((request_id, str(e)))
        print(f"Request {request_id} failed: {e}")

    start_time = time.time()

    types = ["LOGIN", "LOGIN_ERROR"]
    timestamp = int(time.time())
    payload_webhook = {
        "type": types[random.randint(0, 1)],
        "id": event_id,
        "timestamp": timestamp,
        "version": "2.0",
        "authContextModel": {
            "client": client_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "system_language": system_language,
            "screen_resolution": screen_resolution,
        },
        "data": {
            "user_id": user_id,
            "user_email": "test@example.com",
            "username": "stree_test",
            "event_timestamp": timestamp,
            "error": "",
            "auth_context_hash": "jj",
        },
    }

    try:
        async with session.post(
            WEBHOOK_URL, params=params, json=payload_webhook, headers=headers
        ) as response:
            resp_text = await response.text()
            latency = time.time() - start_time
            latencies.append(latency)
            responses.append((request_id, response.status, resp_text))
            print(
                f"Webhook Request {request_id}: Status {response.status}, Time {latency:.2f}s -> {resp_text}"
            )
    except Exception as e:
        errors.append((request_id, str(e)))
        print(f"Webhook Request {request_id} failed: {e}")


async def worker(session, interval, duration, max_requests):
    global total_requests_sent, request_id
    global time_to_response
    start_time = time.time()

    while (time.time() - start_time < duration) and (
        total_requests_sent < max_requests
    ):
        async with lock:
            if total_requests_sent >= max_requests:
                break
            total_requests_sent += 1
            request_id += 1
            current_request_id = request_id

        await make_request(session, current_request_id)
        await asyncio.sleep(interval / 1000)
    time_to_response = time.time() - start_time


async def run_requests(workers, interval, duration, max_requests):
    async with aiohttp.ClientSession() as session:
        tasks = [
            worker(session, interval, duration, max_requests) for _ in range(workers)
        ]
        await asyncio.gather(*tasks)


def print_metrics():
    print("\nMetrics Summary:")
    print(f"Total time: {(time_to_response):.2f}s")
    print(f"Total Requests Sent: {total_requests_sent*2}")
    print(f"Total Responses Received: {len(responses)}")
    print(f"Total Errors: {len(errors)}")
    if latencies:
        print(f"Average Latency: {mean(latencies):.2f}s")
        print(f"Min Latency: {min(latencies):.2f}s")
        print(f"Max Latency: {max(latencies):.2f}s")
        print(f"Percentile p90: {np.percentile(latencies, 90):.2f}s")
        print(f"Percentile p95: {np.percentile(latencies, 95):.2f}s")
        print(f"Percentile p99: {np.percentile(latencies, 99):.2f}s")


def parse_args():
    parser = argparse.ArgumentParser(description="Stress test iam-amfa.")
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Number of workers to send requests concurrently.",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=DEFAULT_REQUEST_INTERVAL,
        help="Interval between requests in milliseconds.",
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=DEFAULT_DURATION,
        help="Duration to run the requests in seconds.",
    )
    parser.add_argument(
        "-t",
        "--total_requests",
        type=int,
        default=None,
        help="Total number of requests to send. If not specified, calculated from interval and duration.",
    )
    parser.add_argument(
        "-s",
        "--single",
        action="store_true",
        help="Send a single request with one worker only.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.single:
        workers = 1
        total_requests = 1
        duration = 1
        interval = 1
    else:
        workers = args.workers
        duration = args.duration
        interval = args.interval
        total_requests = (
            args.total_requests
            or int(args.duration * 1000 / args.interval) * args.workers
        )

    asyncio.run(run_requests(workers, interval, duration, total_requests))
    print_metrics()
