export const SCENARIOS = [
  {
    id: "paper",
    name: "单篇论文问答",
    question: "请解释 ResNet 中残差连接的作用。",
    skill: "paper-qa",
  },
  {
    id: "comparison",
    name: "多篇论文比较",
    question: "比较 ResNet 与 ViT 的归纳偏置和训练特点。",
    skill: "paper-comparison",
  },
  {
    id: "diagnosis",
    name: "训练日志诊断",
    question: "训练损失下降，但验证损失上升，该如何排查？",
    skill: "training-diagnosis",
  },
  {
    id: "planning",
    name: "实验方案规划",
    question: "只有 8GB 显存，如何规划图像分类微调实验？",
    skill: "experiment-planning",
  },
  {
    id: "insufficient",
    name: "证据不足",
    question: "这些模型在我的私有数据集上能达到多少准确率？",
    skill: "paper-qa",
  },
  {
    id: "failure",
    name: "任务失败",
    question: "演示工具故障与失败重试。",
    skill: "training-diagnosis",
  },
  {
    id: "partial",
    name: "部分回答",
    question: "资料不完整时，给出可用的部分分析。",
    skill: "paper-qa",
  },
];
export function seed() {
  const projects = [
    {
      project_id: "project_vision",
      name: "视觉表征研究",
      description: "残差网络、视觉 Transformer 与训练实验",
    },
    {
      project_id: "project_medical",
      name: "医学图像分割",
      description: "独立的资料库、会话与任务空间",
    },
  ];
  const documents = projects.flatMap((p, i) =>
    (i ? ["分割实验记录.txt"] : ["ResNet.pdf", "ViT.pdf", "training.csv"]).map(
      (name, j) => ({
        document_id: `${p.project_id}_doc_${j}`,
        project_id: p.project_id,
        name,
        type: name.split(".").pop(),
        status: "ready",
        demo: true,
        seeded: true,
      }),
    ),
  );
  const threads = projects.map((p) => ({
    thread_id: `${p.project_id}_welcome`,
    project_id: p.project_id,
    title: "开始一次科研探索",
  }));
  return { version: 1, projects, documents, threads, messages: [], runs: {} };
}
export function resultFor(run, documents) {
  const demo = documents.filter(
    (d) => d.project_id === run.project_id && d.status === "ready" && d.seeded,
  );
  const selected =
    run.scenario === "diagnosis"
      ? demo.filter((d) => d.type === "csv")
      : demo
          .filter((d) => d.type === "pdf")
          .slice(0, run.scenario === "comparison" ? 2 : 1);
  const insufficient =
    run.scenario === "insufficient" ||
    selected.length === 0 ||
    (run.scenario === "comparison" && selected.length < 2);
  const evidence = insufficient
    ? []
    : selected.map((d, i) => ({
        evidence_id: `${run.run_id}_e${i + 1}`,
        run_id: run.run_id,
        project_id: run.project_id,
        document_id: d.document_id,
        document_name: d.name,
        page_number: d.type === "pdf" ? 3 + i : null,
        snippet:
          d.type === "csv"
            ? "演示日志：epoch 20 → 40，train_loss 0.42 → 0.18，val_loss 0.51 → 0.67。"
            : i
              ? "演示证据：ViT 将图像分割为 patch，使用自注意力建模全局关系。此片段为人工编写，并非论文原文。"
              : "演示证据：残差块将输入通过跳跃连接与残差映射相加，形式为 y = F(x) + x。此片段为人工编写，并非论文原文。",
      }));
  const summaries = {
    paper:
      "## 残差连接让深层网络更容易优化\n\n残差块学习相对于输入的变化，并通过跳跃连接保留输入信息。这有助于缓解深层网络的优化困难，但不保证所有设置下都提升泛化性能。\n\n```python\n# 结构示意，非完整训练代码\ny = residual_block(x) + x\n```\n\n| 对比项 | 普通网络 | 残差网络 |\n| --- | --- | --- |\n| 学习目标 | 目标映射 | 残差映射 |\n| 信息路径 | 逐层传递 | 增加跳跃路径 |",
    comparison:
      "## ResNet 与 ViT：从局部结构到全局关系\n\n| 维度 | ResNet | ViT |\n| --- | --- | --- |\n| 核心结构 | 卷积与残差连接 | Patch 与自注意力 |\n| 归纳偏置 | 局部性与平移等变性 | 更少的图像先验 |\n| 实验重点 | 深度与正则化 | 预训练与数据规模 |\n\n应统一数据划分、预训练条件和计算预算后再比较，不能直接用不同论文中的指标排序。",
    diagnosis:
      "## 优先检查过拟合与验证流程\n\n演示日志中训练损失持续下降，验证损失却上升。这与过拟合相符，但仍需排除数据分布变化与验证实现问题。\n\n1. 固定验证集并检查数据泄漏。\n2. 检查 `model.eval()` 与数据预处理。\n3. 对比早停、权重衰减与增强策略。",
    planning:
      "## 先建立低成本、可复现的基线\n\n从预训练 ResNet 的线性探测开始，再逐步解冻。固定随机种子和验证划分；记录峰值显存与吞吐量。8GB 是否足够仍取决于输入分辨率与批量大小。",
    partial:
      "## 当前可确认的部分\n\n演示资料可以说明残差块的结构，尚不能对你的数据集给出性能预测。下面只列出有演示证据支持的内容。",
  };
  return {
    evidence,
    answer: {
      status: insufficient
        ? "insufficient_evidence"
        : run.scenario === "partial"
          ? "partial"
          : "complete",
      summary: insufficient
        ? "## 现有证据不足\n\n当前资料无法支持这个问题的确定结论。请提供匹配的论文、数据集说明或完整训练日志。上传文件在此原型中不会被真实分析。"
        : summaries[run.scenario] || summaries.paper,
      claims: evidence.map((e) => ({
        statement: e.snippet
          .replace("演示证据：", "")
          .replace("演示日志：", ""),
        evidence_ids: [e.evidence_id],
      })),
      hypotheses:
        !insufficient && ["diagnosis", "planning"].includes(run.scenario)
          ? [
              {
                hypothesis: "较强正则化可能改善验证表现。",
                confidence: 0.65,
                validation_method:
                  "固定划分与种子，仅改变权重衰减进行对照实验。",
              },
            ]
          : [],
      experiments:
        !insufficient && ["planning", "diagnosis"].includes(run.scenario)
          ? [
              {
                objective: "建立稳定的微调基线",
                change: "冻结主干训练分类头，再解冻最后一个阶段",
                metrics: ["验证准确率", "峰值显存", "训练耗时"],
                success_criteria:
                  "多种子平均验证准确率改善，且峰值显存低于设备上限。",
              },
            ]
          : [],
      missing_information:
        insufficient || run.scenario === "partial"
          ? ["数据集规模与固定划分", "训练配置、评估指标和实际日志"]
          : [],
    },
  };
}
