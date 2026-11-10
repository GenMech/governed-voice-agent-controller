"""Small HTTP boundary for the simulator."""

import time

import httpx


class Api:
    def __init__(self, url: str):
        self.client = httpx.Client(base_url=url, timeout=120)

    def close(self):
        self.client.close()

    def request(self, method: str, path: str, **kwargs) -> dict | list:
        for attempt in range(4):
            try:
                response = self.client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 3:
                    raise
                time.sleep(0.25 * (2 ** attempt))
                continue
            if response.status_code >= 500 and attempt < 3:
                time.sleep(0.25 * (2 ** attempt))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("unreachable")

    def lines(self, path: str):
        with self.client.stream("GET", path) as response:
            response.raise_for_status()
            yield from response.iter_lines()
