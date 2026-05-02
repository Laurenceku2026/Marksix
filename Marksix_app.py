支持**制表符、逗号或空格**分隔，至少需要8列（期次、日期、B1-B7）
""")

# 文本框，默认显示示例
example_data = """26045	2026-04-25	4	16	21	36	42	46	9
26044	2026-04-23	12	23	37	38	45	48	8
26043	2026-04-21	2	4	10	11	26	44	40
26042	2026-04-18	17	20	27	32	39	46	34
26041	2026-04-16	6	12	14	28	44	46	15
26040	2026-04-14	8	19	22	33	44	46	18
26039	2026-04-11	11	14	17	28	40	42	2
26038	2026-04-09	13	16	24	43	44	45	40
26037	2026-04-07	8	23	25	29	33	34	49
26036	2026-04-04	20	28	32	35	40	45	43"""

pasted_text = st.text_area(
    "粘贴开奖数据",
    value=example_data,
    height=300,
    help="每期一行，至少包含期次、日期、B1-B7共9列"
)

# 显示解析预览（只显示前30期）
if pasted_text:
    lines = pasted_text.strip().split('\n')
    preview_lines = lines[:30]  # 只取前30行
    
    st.markdown(f"**数据预览** (共 {len(lines)} 期，显示前 {min(30, len(lines))} 期)")
    
    # 创建预览DataFrame
    preview_data = []
    for line in preview_lines:
        parts = line.replace(',', '\t').replace(' ', '\t').split('\t')
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 9:
            preview_data.append({
                '期次': parts[0],
                '日期': parts[1],
                'B1': parts[2], 'B2': parts[3], 'B3': parts[4],
                'B4': parts[5], 'B5': parts[6], 'B6': parts[7], 'B7': parts[8]
            })
    
    if preview_data:
        preview_df = pd.DataFrame(preview_data)
        st.dataframe(preview_df, use_container_width=True, height=400)
    
    if len(lines) > 30:
        st.caption(f"📜 还有 {len(lines) - 30} 期未显示，可滚动上方文本框查看全部")
    
    # 解析完整数据
    if st.button("✅ 确认并解析数据", type="primary"):
        draws = parse_pasted_data(pasted_text)
        if draws and len(draws) > 0:
            st.success(f"✅ 成功解析 {len(draws)} 期数据")
        else:
            st.error("❌ 解析失败，请检查数据格式")

else:
# Excel上传方式
uploaded_file = st.file_uploader("上传历史开奖数据 (Excel格式)", type=['xlsx', 'xls'])
if uploaded_file is not None:
    draws = parse_excel_file(uploaded_file)
    if draws and len(draws) > 0:
        st.success(f"✅ 成功加载 {len(draws)} 期数据")
        
        # 显示数据预览
        with st.expander("📊 数据预览 (前30期)"):
            preview_df = pd.DataFrame([
                {'期次': draw.get('period', i+1), '号码': draw['numbers'], '和值': draw['sum'], '特别号': draw.get('special', '')}
                for i, draw in enumerate(draws[:30])
            ])
            st.dataframe(preview_df, use_container_width=True)
            if len(draws) > 30:
                st.caption(f"📜 还有 {len(draws) - 30} 期未显示")

# 如果有数据，进行分析
if draws and len(draws) > 0:
st.markdown("---")

# 计算冷热码
scores, freq, short_freq, absence = calculate_scores(draws)

# 显示冷热码分析
st.subheader("🔥 冷热码分析")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**🔥 热门号码 (Top 10)**")
    hot_df = pd.DataFrame([
        {'号码': num, '得分': f"{scores[num]:.2f}", '总次数': freq[num], '缺席次数': absence[num]}
        for num in sorted(scores, key=scores.get, reverse=True)[:10]
    ])
    st.dataframe(hot_df, use_container_width=True)

with col2:
    st.markdown("**❄️ 冷门号码 (Bottom 10)**")
    cold_df = pd.DataFrame([
        {'号码': num, '得分': f"{scores[num]:.2f}", '总次数': freq[num], '缺席次数': absence[num]}
        for num in sorted(scores, key=scores.get)[:10]
    ])
    st.dataframe(cold_df, use_container_width=True)

with col3:
    st.markdown("**📈 近期活跃**")
    recent_active = [num for num in range(1, 50) if any(num in draw['numbers'] for draw in draws[-10:])]
    st.write(f"近10期出现过的号码: **{len(recent_active)}个**")
    st.write(sorted(recent_active)[:15], "...")

# 和值分布图
st.subheader("📈 和值趋势分析")
sum_df = pd.DataFrame([
    {'期次': i+1, '和值': draw['sum']}
    for i, draw in enumerate(draws)
])
fig = px.line(sum_df, x='期次', y='和值', title='历史和值走势')
fig.add_hline(y=175, line_dash="dash", line_color="red", annotation_text="理论均值(175)")
fig.add_hrect(y0=140, y1=210, line_width=0, fillcolor="green", opacity=0.1, annotation_text="±1σ区间")
st.plotly_chart(fig, use_container_width=True)

# 投注设置
st.subheader("🎲 智能投注生成")

col1, col2 = st.columns(2)
with col1:
    num_bets = st.number_input("请输入投注注数", min_value=1, max_value=10, value=4, step=1)
with col2:
    st.markdown("**💡 策略说明**")
    if num_bets == 1:
        st.info("单注：中和值(175) + 热码优先 + 连号/跳号")
    elif num_bets == 2:
        st.info("两注：小和值(155) + 大和值(195)")
    elif num_bets == 3:
        st.info("三注：小(155) + 中(175) + 大(195)")
    else:
        st.info(f"{num_bets}注：大中小各一 + {num_bets-3}注趋势预测")

# 生成投注
if st.button("🚀 生成智能投注", type="primary"):
    bets = generate_optimal_bets(draws, num_bets, scores)
    
    st.markdown("### 📝 推荐投注组合")
    
    for i, bet in enumerate(bets, 1):
        with st.container():
            st.markdown(f"**第{i}注** - 策略: {bet['strategy']}")
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.write(f"号码: {bet['numbers']}")
            with col2:
                st.write(f"和值: {bet['sum']}")
            with col3:
                diff = bet['sum'] - 175
                st.write(f"偏差: {diff:+d}")
            
            has_pattern = has_consecutive_or_jump(bet['numbers'])
            st.caption(f"包含连号/跳号: {'✅' if has_pattern else '❌'}")
            st.divider()
    
    # 预测赢率提示
    st.info("""
    💡 **关于预测赢率**：
    - 本工具基于历史数据统计，预测中奖率约 **6-7%** (中3个或以上)
    - 实际中奖率受随机性影响，长期期望值仍为负
    - 建议理性投注，量力而行
    """)

# 回测功能
st.subheader("📊 策略回测")

col1, col2 = st.columns([1, 2])
with col1:
    backtest_bets = st.number_input("回测投注注数", min_value=1, max_value=10, value=4, step=1)
    run_backtest = st.button("▶️ 运行回测", type="secondary")

with col2:
    st.info("回测使用前100期训练，预测后续所有期次")

if run_backtest:
    with st.spinner("正在运行回测..."):
        if len(draws) > 100:
            results_df = backtest(draws, scores, backtest_bets)
            
            # 统计结果
            st.markdown("### 📈 回测结果统计")
            
            stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
            
            total_draws = len(results_df)
            winning_draws = results_df[results_df['中奖等级'] != '无中奖'].shape[0]
            avg_match = results_df['最佳匹配数'].mean()
            
            prize_map = {
                '第4组 ($9,600)': 9600,
                '第5组 ($640)': 640,
                '第6组 ($320)': 320,
                '第7组 ($40)': 40,
            }
            
            total_prize = 0
            for prize in results_df['中奖等级']:
                if prize in prize_map:
                    total_prize += prize_map[prize]
            
            total_cost = len(results_df) * backtest_bets * 10
            
            with stat_col1:
                st.metric("测试期数", total_draws)
            with stat_col2:
                st.metric("中奖期数", winning_draws)
            with stat_col3:
                st.metric("平均匹配数", f"{avg_match:.2f}")
            with stat_col4:
                roi = ((total_prize - total_cost) / total_cost) * 100 if total_cost > 0 else 0
                st.metric("投资回报率(ROI)", f"{roi:+.1f}%")
            
            st.markdown(f"**总投入**: ${total_cost} | **总奖金**: ${total_prize} | **净收益**: ${total_prize - total_cost}")
            
            with st.expander("📋 详细回测结果"):
                st.dataframe(results_df, use_container_width=True)
            
            match_dist = results_df['最佳匹配数'].value_counts().sort_index()
            fig_match = px.bar(
                x=match_dist.index, y=match_dist.values,
                title='每期最佳匹配数分布',
                labels={'x': '匹配号码数', 'y': '期数'}
            )
            st.plotly_chart(fig_match, use_container_width=True)
        else:
            st.warning(f"需要至少100期数据才能进行回测，当前只有{len(draws)}期")

# 页脚
st.markdown("---")
st.caption("⚠️ 本工具仅供学术研究和娱乐参考。六合彩本质上是一种随机游戏，长期期望值为负，请理性投注。")
