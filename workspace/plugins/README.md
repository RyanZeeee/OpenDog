# Plugins

这里放自定义工具插件。

每个插件可以是一个独立文件夹，并提供 `plugin.py`：

```text
workspace/plugins/my-tool/
└── plugin.py
```

`plugin.py` 里需要提供一个注册函数：

```python
def register_tools(registry):
    registry.register(your_tool)
```

`your_tool` 可以用 `opendog.tools.base.tool` 装饰器创建。
