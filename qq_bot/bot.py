import nonebot
from nonebot.adapters.qq import Adapter as QQAdapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(QQAdapter)
nonebot.load_plugin("src.plugins.alaya_qa")
nonebot.run()
