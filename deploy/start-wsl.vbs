' 笼中仙 — Windows 开机自启 WSL2
' 安装方法: 将此文件复制到 shell:startup 目录
'   1. Win+R 输入 shell:startup 回车
'   2. 将 start-wsl.vbs 复制到打开的目录中
'
' WSL2 启动后 systemd 会自动拉起 longzhongxian 服务

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "wsl -d Ubuntu", 0, False
Set WshShell = Nothing
