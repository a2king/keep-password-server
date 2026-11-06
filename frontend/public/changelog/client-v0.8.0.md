---
version: v0.8.0
date: 2026-10-30
product: client
title: 正式同步域名与 Edge 扩展包
source: https://github.com/a2king/keep-password/releases/tag/v0.8.0
---

- 云同步默认地址改为 `https://api.keep-password.work`。新绑定时按地址列表探测可用主机；已经绑定的设备仍使用当时保存的地址
- 浏览器和桌面自动填充的候选账号按网站地址相似度排序
- 网页候选框跟随页面滚动，并限制一次可见的行数
- 设置页可以打开 Edge 扩展商店
- 发布包增加 Edge 扩展压缩包，内容与 Chrome 扩展包相同

Windows 请使用安装包或便携包，不需要另外安装 .NET。浏览器扩展装好后，仍需在本机注册一次 Native Messaging 宿主。
