# Regression: for x in self.dict_attr[key] inside methods
# Previously crashed because the compiler fell back to CPython bridge
# iteration on a native FpyList pointer (not a PyObject*).

class EventEmitter:
    def __init__(self):
        self.listeners = {}

    def on(self, event, callback):
        if event not in self.listeners:
            self.listeners[event] = []
        self.listeners[event].append(callback)

    def emit(self, event, data):
        if event in self.listeners:
            for cb in self.listeners[event]:
                cb(data)

emitter = EventEmitter()
log = []

def on_click(data):
    log.append(f"clicked: {data}")

def on_hover(data):
    log.append(f"hovered: {data}")

emitter.on("click", on_click)
emitter.on("hover", on_hover)
emitter.emit("click", "button1")
emitter.emit("hover", "link2")
emitter.emit("click", "button3")
print(log)
