""")

check_text = st.text_area("粘贴兑奖数据", height=200, key="check_text_area")

if st.button("🔍 查奖", key="check_prize_btn"):
    if check_text.strip():
        check_draws = parse_check_draws(check_text)
        if check_draws:
            st.success(f"成功解析 {len(check_draws)} 期数据")
            bets = st.session_state['generated_bets']
            result_data = []
            for i, bet in enumerate(bets, 1):
                numbers_sorted = sorted(bet['numbers'])
                numbers_display = ' '.join(str(n) for n in numbers_sorted)
                row = {'注数': i, '推荐号码': numbers_display, '和值': bet['sum'], '目标策略': bet['target'], '偏差': f"{bet['deviation']:+d}" if bet['deviation'] != 0 else "0"}
                for draw in check_draws:
                    match_count = calculate_match_count(numbers_sorted, draw['numbers'], draw['special'])
                    row[f"{draw['period']}期"] = f"{match_count:.1f}"
                result_data.append(row)
            st.dataframe(pd.DataFrame(result_data), use_container_width=True, hide_index=True)
            
            st.markdown("**📊 查奖统计**")
            stats_data = []
            for draw in check_draws:
                matches = [float(row[f"{draw['period']}期"]) for row in result_data if f"{draw['period']}期" in row]
                if matches:
                    match_3plus = len([m for m in matches if m >= 3])
                    match_3half_plus = len([m for m in matches if m >= 3.5])
                    stats_data.append({
                        '期次': draw['period'],
                        '日期': draw['date'],
                        '平均中奖个数': f"{np.mean(matches):.2f}",
                        '最高中奖个数': f"{max(matches):.1f}",
                        '中3个以上注数': match_3plus,
                        '中3.5个以上注数': match_3half_plus
                    })
            if stats_data:
                st.dataframe(pd.DataFrame(stats_data), use_container_width=True, hide_index=True)
        else:
            st.error("数据解析失败，请检查格式")
    else:
        st.warning("请粘贴兑奖数据")


st.markdown("---")
st.caption("⚠️ 本工具仅供学术研究和娱乐参考。六合彩本质上是一种随机游戏，长期期望值为负，请理性投注。")
