# B-05-announcements-P1P2｜2026-11-11 北京时间
- Chief紧急派单，原头cef9de0317a2139b59557815aed3732cef1e6dc0；在原ds/B-05-announcements追加，不改共享文件/原夹具。
- P1：先把反斜杠规范化为正斜杠，再解析实际主机与HTTPS白名单；仅返回同一份已校验字符串，url_host与实际输出主机一致。
- 反例https://outside.example\@<白名单主机>/synthetic.pdf降为url=null，url_host=outside.example，不误标白名单。
- P2：逐条捕获解析ValueError（含畸形IPv6/非法端口）；只将该条url/url_host置null，整页与同页正常公告保持可读。
- 同时拒绝ASCII空白/控制字符及用户信息authority；有效白名单反斜杠路径按规范化结果返回。
- 先跑新回归：1个绕过+2个畸形用例在原实现均真失败（3 failed）；修复后显式公告文件-k b05_announcements，44 passed。
- 新增9例含两类精确负例、同页两条保留/200/缓存头、2条正常规范化对照与4类歧义authority拒绝；原权限/归属/游标/生产拒装均复跑。
- Ruff仅查改动2模块通过；mypy仅公告生产模块通过；证据F:/workspace/team/status/B-05-announcements-P1P2-{red,green}.xml。
- 独立Node WHATWG解析核对8条实际过滤输出，其中2条可见链接均为同一白名单主机；精确反例浏览器主机=outside.example，网络调用0；证据同status目录P1P2-browser-*。
- B-13配套说明：19场景/124字段路径无增删；原输入19/19通过路由模型，显式本地HTTP仅13/19逐值相等，模型通过不等于路由语义相等。
- factors原四场景均含旧合成日期/版本，stock另有非空行与计数；#71按T-A158归零并令无请求日期/版本/时点null，不能直送原夹具作为HTTP预期。
- factors原证书场景在当前占位源降为no_source，尚无证书读取链；有请求日期按请求透传。详表另在B-13独立main文档分支交付。
- files/staged/完整推出范围secret_scan+gitleaks双扫门禁与diff检查见提交/PR留卡，不以既有扫描代替本次。
- 全部纯合成、内存SQLite/会话；无网络链接访问、生产库/真实麦蕊/凭据、合并或部署；B-06/r2不动。
- DeepSeek：复用B-03已核夹具草稿；本次安全修复、精确反例与结论自行完成，未外包。
申请新任务：请复核冻结本次新头增量核销P1/P2；B-13文档接续完成，B-06仍按既有门槛。
