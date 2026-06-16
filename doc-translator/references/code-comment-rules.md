# 代码块注释规则（详细注释版）

> 本文件从 SKILL.md 拆分。核心原则：**翻译后的代码块应附带足够详细的注释，帮助读者理解代码的意图、算法逻辑和设计理由**，而不仅仅是"这段代码在做什么"。

---

## 三层深度模型

每条注释应尽可能覆盖以下层次：

| 层次 | 回答的问题 | 示例 |
|------|-----------|------|
| **WHAT**（做什么） | 这段代码在做什么？ | `对输入数据进行标准化处理` |
| **HOW**（怎么做） | 为什么用这个方法？ | `使用 Z-score 标准化而非 MinMax，因为数据存在离群值` |
| **WHY**（为什么） | 为什么这个步骤重要？它对后面的影响是什么？ | `标准化后梯度下降收敛更快，且各特征的权重可比` |

- 简单辅助逻辑：至少覆盖 WHAT
- 核心算法逻辑：必须覆盖 HOW 和 WHY
- 复杂的多步算法：用多段注释块说明策略，再用行内注释标注关键转折点

---

## 密度指南（按代码类型）

不是所有代码块都需要相同密度的注释。以下指南根据常见文档类型划分：

### 模型训练 / 算法实现（最高密度）

**每 5-10 行代码应有 3-8 行注释**。包含：
- 算法策略说明（一段前言注释）
- 关键步骤的 WHY
- 超参数选择理由
- 循环/条件分支的逻辑说明

```python
# 【策略说明】使用小批量梯度下降来平衡收敛速度和内存占用。
# 全批量梯度下降每次更新需要遍历全部数据，在大数据集上很慢；
# 随机梯度下降虽然快但震荡太大。小批量(32)在两者之间取得平衡。
BATCH_SIZE = 32
n_batches = len(X_train) // BATCH_SIZE

for epoch in range(EPOCHS):
    # 每个 epoch 前打乱数据，防止模型学到样本顺序相关的伪模式
    indices = np.random.permutation(len(X_train))
    X_shuffled = X_train[indices]
    y_shuffled = y_train[indices]

    for i in range(n_batches):
        start = i * BATCH_SIZE
        end = start + BATCH_SIZE
        X_batch = X_shuffled[start:end]
        y_batch = y_shuffled[start:end]

        # 前向传播：计算当前批次的预测值
        y_pred = X_batch @ self.weights + self.bias
        # 计算 MSE 损失，用于后续梯度计算
        loss = np.mean((y_pred - y_batch) ** 2)

        # 反向传播：根据链式法则计算梯度
        # dw = (2/n) * X^T * (y_pred - y_true)，来自 MSE 的偏导
        grad_w = (2 / len(X_batch)) * X_batch.T @ (y_pred - y_batch)
        grad_b = (2 / len(X_batch)) * np.sum(y_pred - y_batch)

        # 沿梯度反方向更新参数，学习率控制步长防止 overshoot
        self.weights -= self.lr * grad_w
        self.bias -= self.lr * grad_b
```

### 数据预处理 / 特征工程（中高密度）

**每 5-8 行代码应有 2-5 行注释**。包含：
- 为什么选择这种预处理方式
- 处理后的数据对后续模型的影响

```python
# 处理缺失值：对数值列用中位数填充，因为收入分布是右偏的，
# 中位数比均值更能代表"典型值"，不受高收入离群值影响。
# 对类别列用众数填充，保持类别分布不变。
for col in numeric_cols:
    df[col].fillna(df[col].median(), inplace=True)
for col in categorical_cols:
    df[col].fillna(df[col].mode()[0], inplace=True)

# 对数值特征做 Z-score 标准化：(x - mean) / std
# 标准化后各特征均值为0、方差为1，避免量纲差异导致模型偏向大数值特征
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
```

### 可视化 / 图表生成（中密度）

**每 5-10 行代码应有 2-4 行注释**。包含：
- 图表传达的关键信息
- 视觉编码的选择理由

```python
# 绘制预测值 vs 实际值的散点图，对角线 y=x 表示完美预测。
# 点越靠近对角线，模型拟合越好。用 alpha 透明度处理密集区域重叠。
plt.scatter(y_test, y_pred, alpha=0.6, edgecolors='w', linewidth=0.5)
plt.plot([y.min(), y.max()], [y.min(), y.max()], 'r--', lw=2,
         label='Perfect Prediction')
plt.xlabel('Actual Values')
plt.ylabel('Predicted Values')
plt.title('Prediction vs Actual (Test Set)')
plt.legend()
```

### 简单的 IO / 工具函数（低密度）

每 10-15 行代码 1-2 行注释即可。除非有非自解释的逻辑。

---

## 示例对照库

### 示例 1：训练循环（推荐写法）

```python
# 训练策略：使用 Adam 优化器，它结合了 Momentum（加速收敛）
# 和 RMSProp（自适应学习率）的优点，对稀疏梯度和非平稳目标都有效。
# 初始学习率设为 0.001（Adam 论文推荐的默认值）。
#
# 每个 epoch 遍历全部数据一次，共训练 100 个 epoch。
# 如果验证损失连续 5 个 epoch 不下降，提前停止防止过拟合。
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
    optimizer, mode='min', patience=3, factor=0.5
)

best_val_loss = float('inf')
epochs_no_improve = 0

for epoch in range(100):
    model.train()
    train_loss = 0.0

    for batch_X, batch_y in train_loader:
        optimizer.zero_grad()
        # 前向传播 + 损失计算
        outputs = model(batch_X)
        loss = criterion(outputs, batch_y)
        # 反向传播计算梯度
        loss.backward()
        # 梯度裁剪：防止梯度爆炸，将梯度范数限制在 1.0 以内
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        train_loss += loss.item()

    # 验证阶段：不计算梯度以提高速度并防止 BatchNorm 等层状态改变
    model.eval()
    val_loss = 0.0
    with torch.no_grad():
        for batch_X, batch_y in val_loader:
            outputs = model(batch_X)
            val_loss += criterion(outputs, batch_y).item()

    # 动态调整学习率：验证损失不下降时降低学习率，精细搜索局部最小值
    scheduler.step(val_loss)

    # 早停机制：验证损失连续 patience 个 epoch 不下降就停止训练
    if val_loss < best_val_loss:
        best_val_loss = val_loss
        epochs_no_improve = 0
        torch.save(model.state_dict(), 'best_model.pth')
    else:
        epochs_no_improve += 1
        if epochs_no_improve >= 5:
            print(f"Early stopping at epoch {epoch}")
            break
```

### 示例 2：自定义损失函数

```python
# 自定义 Focal Loss：在交叉熵基础上增加调制因子 (1-p)^gamma，
# 让模型更关注难分类样本，缓解类别不平衡问题。
# gamma=0 时退化为标准交叉熵；gamma=2 是原文推荐的默认值。
#
# 使用场景：目标检测中前景背景极端不平衡（~1:1000）
def focal_loss(y_pred, y_true, gamma=2.0, alpha=0.25):
    # 限制预测值范围防止 log(0) 导致数值不稳定
    y_pred = torch.clamp(y_pred, min=1e-7, max=1-1e-7)
    # 标准交叉熵损失
    ce_loss = -y_true * torch.log(y_pred) - (1 - y_true) * torch.log(1 - y_pred)
    # 调制因子：对易分类样本(p 接近 1)大幅降低其权重，
    # 对难分类样本(p 接近 0)几乎保留原始权重
    p_t = y_true * y_pred + (1 - y_true) * (1 - y_pred)
    modulating_factor = (1 - p_t) ** gamma
    # alpha 平衡因子：为正类样本额外加权，缓解正类稀少的问题
    alpha_factor = y_true * alpha + (1 - y_true) * (1 - alpha)
    return (alpha_factor * modulating_factor * ce_loss).mean()
```

### 示例 3：数据分析与聚合

```python
# 按用户 ID 分组计算月度消费统计：
# - total_spend: 月消费总额，衡量用户价值
# - transaction_count: 交易频次，衡量用户活跃度
# - avg_ticket: 平均客单价，反映消费层级
#
# 这些特征将输入到 RFM 模型中做用户分群
monthly_stats = (df
    .groupby(['user_id', 'year_month'])
    .agg(
        total_spend=('amount', 'sum'),
        transaction_count=('amount', 'count'),
        avg_ticket=('amount', 'mean')
    )
    .reset_index()
)

# 计算用户最近一次消费距今天数(Recency)：
# 以数据截止日期(2024-12-31)为准，recency 越小表示用户越近有消费
reference_date = pd.Timestamp('2024-12-31')
last_purchase = df.groupby('user_id')['transaction_date'].max()
recency = (reference_date - last_purchase).dt.days
```

### 示例 4：模型评估与可解释性

```python
# 评估指标选择说明：
# - RMSE：与 y 单位一致，直观衡量预测误差量级
# - MAE：对所有误差等权，不受极个别大离群值主导
# - R²：衡量模型相对均值基线的提升程度，范围 (-∞, 1]
#
# 同时计算这三个指标，因为单一指标可能掩盖问题：
# RMSE 远大于 MAE 说明存在离群值导致的较大预测误差
y_pred = model.predict(X_test)

rmse = np.sqrt(mean_squared_error(y_test, y_pred))
mae = mean_absolute_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)

print(f"RMSE: {rmse:.2f} (单位: {target_unit})")
print(f"MAE:  {mae:.2f} (单位: {target_unit})")
print(f"R²:   {r2:.4f}")

# 特征重要性排序：基于树模型的 feature_importances_，
# 展示对预测贡献最大的 Top-5 特征。这对向业务方解释模型行为很重要。
if hasattr(model, 'feature_importances_'):
    importance_df = pd.DataFrame({
        'feature': feature_names,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    print("\nTop-5 重要特征（对预测贡献最大）:")
    print(importance_df.head(5).to_string(index=False))
```

### 示例 5：超参数搜索

```python
# 网格搜索超参数：K 近邻的 n_neighbors 和 weight 类型。
# 选择 K 的考虑：K 太小容易过拟合(决策边界过于曲折)，
# K 太大容易欠拟合(决策边界过于平滑)。
# 权重方式：uniform 对所有邻居等权，distance 按距离加权。
param_grid = {
    'n_neighbors': [3, 5, 7, 9, 11],
    'weights': ['uniform', 'distance']
}

# 5 折交叉验证：将训练数据分成 5 份，轮流用 4 份训练 1 份验证，
# 比单次 hold-out 验证更稳定，减少数据划分的随机性影响
grid_search = GridSearchCV(
    KNeighborsClassifier(),
    param_grid,
    cv=5,
    scoring='f1_macro',       # 多分类用 macro F1，对各类别等权
    n_jobs=-1,                # 并行搜索所有组合，充分利用 CPU
    verbose=1
)
grid_search.fit(X_train, y_train)

print(f"最佳参数: {grid_search.best_params_}")
print(f"最佳 CV F1: {grid_search.best_score_:.4f}")
```

---

## 质量检查清单

每写完一段注释，快速自查：

- [ ] 这段注释是否解释了**为什么**这么做，而不只是**做了什么**？
- [ ] 超参数是否有选择理由（为什么用这个值/方法）？
- [ ] 算法步骤是否有策略说明（为什么这个步骤在这里）？
- [ ] 注释的语言风格是否与代码一致（Python `#` / JS `//`）？
- [ ] 注释是否写在代码上方，而不是行尾（短说明除外）？
- [ ] 是否避免了逐行注释的冗余？多条相关行共享一段注释更好。

## 质量等级参考

| 等级 | 特征 | 判断方法 |
|------|------|----------|
| ❌ 浅层 | 只有"做了什么" | `# 计算损失`（太泛） |
| ✅ 充分 | 说明了怎么做+为什么 | `# 使用 Huber Loss，因为它对离群值比 MSE 更鲁棒，同时比 MAE 更平滑` |
| 🌟 详尽 | 策略+逻辑+设计理由 | 多段注释说明算法设计思路，关键步骤解释 WHY，超参数有选择依据 |

## 脚本辅助检测

使用 `scripts/detect_code_comments.py` 自动扫描代码块：

```bash
python3 scripts/detect_code_comments.py <目标文件> --output "$SKILL_SESSION/code_blocks.json"
```

脚本输出包含：
- `needs_comments_at`：需要添加注释的行号列表
- `comment_suggestions`：每行对应的中文注释建议
- 根据优先级过滤（模型训练 > 矩阵运算 > 循环 > 其他），每个代码块最多 5 条注释