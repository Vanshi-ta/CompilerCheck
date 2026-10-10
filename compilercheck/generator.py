"""Deterministic generator of small, well-defined C/C++ programs.

Every template is written to avoid undefined behavior: unsigned arithmetic wraps, signed
values stay far from overflow, shifts are in range, divisors are non-zero, arrays are
indexed in bounds and nothing is read uninitialized. Floating-point programs declare an
explicit comparison tolerance. Output is a pure function of (seed, index, language).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from .errors import CaseLoadError
from .models import Category, Language, ProgramCase, Safety

Rng = random.Random


@dataclass(frozen=True)
class Template:
    name: str
    category: Category
    build: Callable[[Rng], str]
    cpp_only: bool = False
    float_tolerance: float | None = None


def _unsigned_chain(rng: Rng) -> str:
    lines = ["#include <stdio.h>", "#include <stdint.h>", "", "int main(void) {",
             f"    uint32_t x = {rng.randrange(1, 2**32)}u;"]
    for _ in range(rng.randint(4, 10)):
        kind = rng.choice(("mul_add", "xorshift", "rotate", "sub", "add"))
        if kind == "mul_add":
            lines.append(f"    x = x * {rng.randrange(1, 2**16) * 2 + 1}u + {rng.randrange(2**32)}u;")
        elif kind == "xorshift":
            lines.append(f"    x ^= x >> {rng.randint(1, 31)};")
        elif kind == "rotate":
            s = rng.randint(1, 31)
            lines.append(f"    x = (x << {s}) | (x >> {32 - s});")
        elif kind == "sub":
            lines.append(f"    x -= {rng.randrange(2**32)}u;")
        else:
            lines.append(f"    x += {rng.randrange(2**32)}u;")
    lines += ['    printf("%u\\n", (unsigned)x);', "    return 0;", "}"]
    return "\n".join(lines) + "\n"


def _signed_bounded(rng: Rng) -> str:
    return f"""#include <stdio.h>

int main(void) {{
    int a = {rng.randint(1, 500)};
    int b = {rng.randint(1, 500)};
    int acc = 0;
    for (int i = 0; i < {rng.randint(20, 200)}; ++i) {{
        acc += (a * i + b) % {rng.randint(2, 97)};
        acc -= i / {rng.randint(1, 9)};
        if (acc % 2 == 0) {{
            acc += {rng.randint(1, 20)};
        }}
    }}
    printf("%d\\n", acc);
    return 0;
}}
"""


def _boundary(rng: Rng) -> str:
    k = rng.randint(1, 1000)
    return f"""#include <limits.h>
#include <stdio.h>

int main(void) {{
    unsigned u = UINT_MAX;
    u += {k}u;
    unsigned z = 0u;
    z -= {k}u;
    int m = INT_MAX;
    m -= {k};
    int n = INT_MIN;
    n += {k};
    unsigned long long big = ULLONG_MAX;
    big += {k}ull;
    printf("%u\\n%u\\n%d\\n%d\\n%llu\\n", u, z, m, n, big);
    printf("%u\\n%d\\n", 1u << {rng.randint(0, 31)}, INT_MAX / {rng.randint(1, 50)});
    return 0;
}}
"""


def _loops(rng: Rng) -> str:
    return f"""#include <stdio.h>

int main(void) {{
    unsigned long long total = 0;
    for (unsigned i = 1; i <= {rng.randint(50, 500)}; ++i) {{
        if (i % {rng.randint(2, 9)} == 0) {{
            total += i;
        }} else if (i % {rng.randint(2, 9)} == 0) {{
            total += 2ull * i;
        }} else {{
            total ^= i;
        }}
    }}
    unsigned steps = 0;
    unsigned long long n = {rng.randint(1, 5000)};
    while (n != 1) {{
        n = (n % 2 == 0) ? n / 2 : 3 * n + 1;
        ++steps;
    }}
    printf("%llu\\n%u\\n", total, steps);
    return 0;
}}
"""


def _arrays(rng: Rng) -> str:
    n = rng.randint(4, 12)
    return f"""#include <stdio.h>

int main(void) {{
    int arr[{n}];
    for (int i = 0; i < {n}; ++i) {{
        arr[i] = (i * {rng.randint(1, 50)} + {rng.randint(0, 50)}) % {rng.randint(2, 100)};
    }}
    for (int i = 0; i < {n} - 1; ++i) {{
        for (int j = 0; j < {n} - 1 - i; ++j) {{
            if (arr[j] > arr[j + 1]) {{
                int t = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = t;
            }}
        }}
    }}
    unsigned checksum = 0;
    for (int i = 0; i < {n}; ++i) {{
        printf("%d ", arr[i]);
        checksum = checksum * 31u + (unsigned)arr[i];
    }}
    printf("\\n%u\\n", checksum);
    return 0;
}}
"""


def _functions(rng: Rng) -> str:
    return f"""#include <stdio.h>

static unsigned gcd(unsigned a, unsigned b) {{
    while (b != 0) {{
        unsigned t = a % b;
        a = b;
        b = t;
    }}
    return a;
}}

static unsigned long long fib(unsigned n) {{
    return n < 2 ? n : fib(n - 1) + fib(n - 2);
}}

static unsigned long long powmod(unsigned long long base, unsigned exp, unsigned long long mod) {{
    unsigned long long r = 1;
    base %= mod;
    while (exp) {{
        if (exp & 1u) r = r * base % mod;
        base = base * base % mod;
        exp >>= 1;
    }}
    return r;
}}

int main(void) {{
    printf("%u\\n", gcd({rng.randint(1, 100000)}u, {rng.randint(1, 100000)}u));
    printf("%llu\\n", fib({rng.randint(1, 22)}));
    printf("%llu\\n", powmod({rng.randint(2, 1000)}ull, {rng.randint(1, 1000)}u, {rng.randint(2, 2**31 - 1)}ull));
    return 0;
}}
"""


def _structs(rng: Rng) -> str:
    n = rng.randint(3, 10)
    return f"""#include <stdio.h>

struct Item {{
    int id;
    int weight;
    unsigned flags;
}};

static struct Item make_item(int id, int weight) {{
    struct Item it;
    it.id = id;
    it.weight = weight;
    it.flags = (unsigned)(id * 7 + weight) & 0xffu;
    return it;
}}

static int total_weight(const struct Item *items, int count) {{
    int total = 0;
    for (int i = 0; i < count; ++i) {{
        total += items[i].weight;
    }}
    return total;
}}

int main(void) {{
    struct Item items[{n}];
    unsigned mix = 0;
    for (int i = 0; i < {n}; ++i) {{
        items[i] = make_item(i, (i * {rng.randint(1, 40)}) % {rng.randint(2, 60)});
        mix ^= items[i].flags;
    }}
    printf("%d\\n%u\\n", total_weight(items, {n}), mix);
    return 0;
}}
"""


def _floating(rng: Rng) -> str:
    return f"""#include <stdio.h>

int main(void) {{
    double acc = {rng.randint(1, 100)}.0;
    for (int i = 1; i <= {rng.randint(5, 40)}; ++i) {{
        acc = acc * 0.5 + i * 0.125;
    }}
    float f = 1.0f;
    for (int i = 0; i < {rng.randint(3, 20)}; ++i) {{
        f = f * 1.5f - 0.25f;
    }}
    printf("%.12e\\n%.6e\\n", acc, (double)f);
    return 0;
}}
"""


def _optimization_sensitive(rng: Rng) -> str:
    return f"""#include <stdio.h>

int main(void) {{
    volatile unsigned seed = {rng.randrange(1, 2**32)}u;
    unsigned s = seed;
    unsigned acc = 0;
    unsigned dead = 0;
    for (unsigned i = 0; i < {rng.randint(100, 5000)}; ++i) {{
        acc += s * i;
        dead += acc * 3u;
        s = s * 1664525u + 1013904223u;
    }}
    unsigned invariant = {rng.randint(2, 1000)}u * {rng.randint(2, 1000)}u;
    unsigned sum = 0;
    for (unsigned j = 0; j < {rng.randint(10, 300)}; ++j) {{
        sum += j * invariant;
    }}
    (void)dead;
    printf("%u\\n%u\\n", acc, sum);
    return 0;
}}
"""


def _cpp_template(rng: Rng) -> str:
    n, m = rng.randint(3, 8), rng.randint(3, 8)
    ints = ", ".join(str(rng.randint(-1000, 1000)) for _ in range(n))
    uints = ", ".join(f"{rng.randint(0, 100000)}u" for _ in range(m))
    return f"""#include <array>
#include <cstddef>
#include <cstdio>

template <typename T, std::size_t N>
T sum_all(const std::array<T, N>& values) {{
    T total = T();
    for (std::size_t i = 0; i < N; ++i) {{
        total += values[i];
    }}
    return total;
}}

int main() {{
    std::array<int, {n}> a = {{{{{ints}}}}};
    std::array<unsigned, {m}> b = {{{{{uints}}}}};
    std::printf("%d %u\\n", sum_all(a), sum_all(b));
    return 0;
}}
"""


def _cpp_tracker(rng: Rng) -> str:
    ids = rng.sample(range(1, 1000), 4)
    return f"""#include <cstdio>

struct Tracker {{
    int id;
    explicit Tracker(int i) : id(i) {{ std::printf("ctor %d\\n", id); }}
    ~Tracker() {{ std::printf("dtor %d\\n", id); }}
}};

int main() {{
    Tracker a({ids[0]});
    {{
        Tracker b({ids[1]});
        Tracker c({ids[2]});
    }}
    Tracker d({ids[3]});
    return 0;
}}
"""


TEMPLATES: tuple[Template, ...] = (
    Template("unsigned_chain", Category.INTEGER_ARITHMETIC, _unsigned_chain),
    Template("signed_bounded", Category.SIGNED_UNSIGNED, _signed_bounded),
    Template("boundary", Category.BOUNDARY, _boundary),
    Template("loops", Category.LOOPS_CONDITIONALS, _loops),
    Template("arrays", Category.ARRAYS, _arrays),
    Template("functions", Category.FUNCTIONS, _functions),
    Template("structs", Category.STRUCTS, _structs),
    Template("floating", Category.FLOATING_POINT, _floating, float_tolerance=1e-9),
    Template("opt_sensitive", Category.OPTIMIZATION_SENSITIVE, _optimization_sensitive),
    Template("cpp_template", Category.FUNCTIONS, _cpp_template, cpp_only=True),
    Template("cpp_tracker", Category.STRUCTS, _cpp_tracker, cpp_only=True),
)


def generate_cases(seed: int, count: int, language: str = "mixed") -> list[ProgramCase]:
    """Generate ``count`` cases; identical arguments always yield identical programs."""
    if count < 0:
        raise CaseLoadError("count must be non-negative")
    if language not in {"c", "cpp", "mixed"}:
        raise CaseLoadError("language must be one of: c, cpp, mixed")
    pool = [t for t in TEMPLATES if language != "c" or not t.cpp_only]
    cases: list[ProgramCase] = []
    for index in range(count):
        template = pool[index % len(pool)]
        rng = random.Random(f"compilercheck:{seed}:{index}")
        if template.cpp_only or language == "cpp":
            lang = Language.CPP
        elif language == "c":
            lang = Language.C
        else:
            lang = rng.choice((Language.C, Language.CPP))
        cases.append(
            ProgramCase(
                test_id=f"gen-s{seed}-{index:04d}-{template.name}",
                source=template.build(rng),
                language=lang,
                category=template.category,
                safety=Safety.WELL_DEFINED,
                seed=seed,
                float_tolerance=template.float_tolerance,
                description=f"generated from template {template.name}",
                metadata={"origin": "generated", "template": template.name, "index": index},
            )
        )
    return cases
