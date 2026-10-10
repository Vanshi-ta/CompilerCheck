// compilercheck: category=undefined_behavior safety=undefined_behavior flags=-pthread description="unsynchronized data race"
// Two threads increment a plain int without synchronization: a data race, undefined behavior.
#include <cstdio>
#include <thread>

static int counter = 0;

static void work() {
    for (int i = 0; i < 100000; ++i) {
        ++counter;
    }
}

int main() {
    std::thread a(work), b(work);
    a.join();
    b.join();
    std::printf("%d\n", counter);
    return 0;
}
