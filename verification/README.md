独立验收说明

冻结提交：https://github.com/9873199/sqlglot-readonly-policy/commit/05c7feaad36e75c7c1fdae99775c21570e6d3734
实际解释器：3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)]

从冻结提交检出源码，用environment-reviewed.json的解释器和依赖复现各verification目录命令。acceptance-r1内regression仅tests/test_parser.py和tests/test_read_access.py，123通过/426子测试；同目录独立主验收42通过，sql_adapter.py只构造原生ReadPolicy、把原生拒绝转PermissionError并投影三元组，没有补安全逻辑。controls-r1直接测原生API，11通过；scope返回空和异常是显式故障注入。observations-r1为真实录屏命令的原生返回和原始日志，未执行任何SQL。integration gitlink保持原固定提交，另有只读核验记录；该子模块数据库测试未运行。保守分析所有CTE正文是实现公开策略。录屏为另写验证控制台，不是模型生成的业务页面。

每组目录内的 *-command.json 保留真实参数、工作目录、PYTHONPATH、退出码和原始日志位置；test-results.json 与 JUnit XML 保留完整成绩。跨机器运行时把这些绝对路径映射到同一冻结 checkout 和自己的缓存目录，所有 --basetemp、XML 和构建输出均放在缓存里。依赖版本见 environment-reviewed.json。
这些材料在模型单轮结束后生成，与原轨内测试分开，不代表项目方质检通过。原轨和视频只放各自的飞书附件。


冻结产物提交：https://github.com/9873199/sqlglot-readonly-policy/commit/05c7feaad36e75c7c1fdae99775c21570e6d3734
这些独立验收文件在模型首轮结束后生成，不是模型原轨中的测试。
