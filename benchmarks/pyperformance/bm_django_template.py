"""
Django template benchmark from pyperformance (the official CPython benchmark suite).

Tests the performance of the Django template system by having Django generate
a 100x100-cell HTML table.

Source: pyperformance 1.14.0 (bm_django_template/run_benchmark.py)
Adapted for standalone timing (no pyperf dependency).
"""

import time
import django.conf
from django.template import Context, Template


DEFAULT_SIZE = 100


def bench_django_template(size):
    template = Template("""<table>
{% for row in table %}
<tr>{% for col in row %}<td>{{ col|escape }}</td>{% endfor %}</tr>
{% endfor %}
</table>
    """)
    table = [range(size) for _ in range(size)]
    context = Context({"table": table})

    # Warm up
    template.render(context)

    # Timed run (average of 5 iterations)
    ITERATIONS = 5
    t0 = time.perf_counter()
    for _ in range(ITERATIONS):
        template.render(context)
    elapsed = time.perf_counter() - t0

    print("django_template: %.1f ms (%d iterations, %dx%d table)" % (
        elapsed / ITERATIONS * 1000, ITERATIONS, size, size))


if __name__ == "__main__":
    django.conf.settings.configure(TEMPLATES=[{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
    }])
    django.setup()

    bench_django_template(DEFAULT_SIZE)
