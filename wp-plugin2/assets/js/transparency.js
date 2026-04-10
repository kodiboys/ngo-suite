// assets/js/transparency.js
jQuery(document).ready(function($) {
    
    // Vue Component: Donations Stream (DSGVO-konform)
    if (document.getElementById('ta-donations-stream')) {
        new Vue({
            el: '#ta-donations-stream',
            data: {
                donations: [],
                stats: {
                    total: 0,
                    unique_donors: 0,
                    average: 0
                },
                loading: true,
                offset: 0,
                has_more: true
            },
            mounted() {
                this.loadDonations();
                this.startAutoRefresh();
            },
            methods: {
                async loadDonations() {
                    const container = $(this.$el);
                    const projectId = container.data('project-id');
                    const limit = container.data('limit');
                    const anonymize = container.data('anonymize');
                    
                    try {
                        const response = await fetch(`${ta_ajax.api_url}/donations/public`, {
                            headers: {
                                'X-API-Key': this.getApiKey()
                            }
                        });
                        const data = await response.json();
                        
                        this.donations = data.donations;
                        this.stats = data.stats;
                        this.loading = false;
                        
                        this.renderDonations();
                    } catch (error) {
                        console.error('Error loading donations:', error);
                        this.showError();
                    }
                },
                
                renderDonations() {
                    const layout = $(this.$el).data('layout');
                    const showAmounts = $(this.$el).data('show-amounts') === 'true';
                    const showDates = $(this.$el).data('show-dates') === 'true';
                    
                    let html = '';
                    
                    if (layout === 'grid') {
                        html = '<div class="ta-donations-grid">';
                        this.donations.forEach(donation => {
                            html += this.renderDonationCard(donation, showAmounts, showDates);
                        });
                        html += '</div>';
                    } else if (layout === 'list') {
                        html = '<div class="ta-donations-list">';
                        this.donations.forEach(donation => {
                            html += this.renderDonationListItem(donation, showAmounts, showDates);
                        });
                        html += '</div>';
                    } else {
                        // Timeline layout
                        html = '<div class="ta-donations-timeline">';
                        this.donations.forEach(donation => {
                            html += this.renderDonationTimeline(donation, showAmounts, showDates);
                        });
                        html += '</div>';
                    }
                    
                    $(this.$el).find('.ta-stream-content').html(html);
                    $(this.$el).find('#ta-total-donations').text(this.formatNumber(this.stats.total));
                    $(this.$el).find('#ta-unique-donors').text(this.stats.unique_donors);
                    $(this.$el).find('#ta-avg-donation').text(this.formatCurrency(this.stats.average));
                    
                    // Animation einblenden
                    $(this.$el).find('.ta-stream-container').fadeIn();
                    $(this.$el).find('.ta-loading').hide();
                },
                
                renderDonationCard(donation, showAmounts, showDates) {
                    return `
                        <div class="ta-donation-card">
                            <div class="ta-donation-icon">
                                <i class="fas fa-${donation.type === 'MONETARY' ? 'euro-sign' : 'box-open'}"></i>
                            </div>
                            <div class="ta-donation-info">
                                <div class="ta-donor-name">
                                    <i class="fas fa-user"></i> ${donation.donor_name || 'Anonym'}
                                </div>
                                ${showAmounts ? `
                                    <div class="ta-donation-amount">
                                        ${this.formatCurrency(donation.amount)}
                                    </div>
                                ` : ''}
                                ${donation.project_name ? `
                                    <div class="ta-donation-project">
                                        <i class="fas fa-folder-open"></i> ${donation.project_name}
                                    </div>
                                ` : ''}
                                ${showDates ? `
                                    <div class="ta-donation-date">
                                        <i class="far fa-calendar-alt"></i> ${moment(donation.donation_date).format('DD.MM.YYYY')}
                                    </div>
                                ` : ''}
                                ${donation.message ? `
                                    <div class="ta-donation-message">
                                        "${this.truncate(donation.message, 100)}"
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    `;
                },
                
                renderDonationListItem(donation, showAmounts, showDates) {
                    return `
                        <div class="ta-donation-list-item">
                            <div class="ta-list-left">
                                <span class="ta-donor-badge">${donation.donor_name ? donation.donor_name.charAt(0) : 'A'}</span>
                            </div>
                            <div class="ta-list-content">
                                <div class="ta-list-name">${donation.donor_name || 'Anonym'}</div>
                                ${showAmounts ? `<div class="ta-list-amount">${this.formatCurrency(donation.amount)}</div>` : ''}
                                ${showDates ? `<div class="ta-list-date">${moment(donation.donation_date).format('DD.MM.YYYY')}</div>` : ''}
                            </div>
                        </div>
                    `;
                },
                
                renderDonationTimeline(donation, showAmounts, showDates) {
                    return `
                        <div class="ta-timeline-item">
                            <div class="ta-timeline-badge">
                                <i class="fas fa-heart"></i>
                            </div>
                            <div class="ta-timeline-content">
                                <div class="ta-timeline-header">
                                    <span class="ta-timeline-name">${donation.donor_name || 'Anonym'}</span>
                                    ${showDates ? `<span class="ta-timeline-date">${moment(donation.donation_date).fromNow()}</span>` : ''}
                                </div>
                                ${showAmounts ? `<div class="ta-timeline-amount">${this.formatCurrency(donation.amount)}</div>` : ''}
                            </div>
                        </div>
                    `;
                },
                
                formatNumber(num) {
                    return new Intl.NumberFormat('de-DE').format(num);
                },
                
                formatCurrency(amount) {
                    return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(amount);
                },
                
                truncate(str, length) {
                    if (str.length <= length) return str;
                    return str.substr(0, length) + '...';
                },
                
                startAutoRefresh() {
                    const interval = ta_ajax.refresh_interval;
                    setInterval(() => {
                        this.loadDonations();
                    }, interval);
                },
                
                showError() {
                    $(this.$el).find('.ta-loading').html(`
                        <div class="ta-error">
                            <i class="fas fa-exclamation-triangle"></i>
                            <p>Fehler beim Laden der Daten. Bitte versuchen Sie es später erneut.</p>
                            <button class="ta-retry-btn">Erneut versuchen</button>
                        </div>
                    `);
                }
            }
        });
    }
    
    // Chart.js für Projektfortschritt
    if (document.getElementById('ta-project-progress')) {
        // Initialisiere Chart
        function initProjectProgress() {
            const ctx = document.getElementById('ta-funding-chart');
            if (!ctx) return;
            
            const fundingPercent = parseInt($('#ta-funding-percent').text());
            
            new Chart(ctx, {
                type: 'doughnut',
                data: {
                    datasets: [{
                        data: [fundingPercent, 100 - fundingPercent],
                        backgroundColor: ['#10b981', '#e5e7eb'],
                        borderWidth: 0,
                        cutout: '70%'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        tooltip: { enabled: false },
                        legend: { display: false }
                    }
                }
            });
        }
        
        // Lade Projektdaten
        async function loadProjectData(projectId) {
            try {
                const response = await fetch(`${ta_ajax.api_url}/project/${projectId}`);
                const data = await response.json();
                
                $('#ta-project-name').text(data.name);
                $('#ta-funding-percent').text(data.funding_percentage);
                $('#ta-budget-planned').text(formatCurrency(data.budget_planned));
                $('#ta-donations-received').text(formatCurrency(data.donations_received));
                $('#ta-remaining-need').text(formatCurrency(data.budget_planned - data.donations_received));
                $('#ta-progress-fill').css('width', `${data.funding_percentage}%`);
                
                // Expense Breakdown Chart
                if ($('#ta-expense-breakdown').is(':visible')) {
                    const expenseCtx = document.getElementById('ta-expense-chart');
                    if (expenseCtx && data.expenses) {
                        new Chart(expenseCtx, {
                            type: 'bar',
                            data: {
                                labels: data.expenses.map(e => e.category),
                                datasets: [{
                                    label: 'Ausgaben (€)',
                                    data: data.expenses.map(e => e.amount),
                                    backgroundColor: '#ef4444'
                                }]
                            },
                            options: {
                                responsive: true,
                                plugins: {
                                    legend: { position: 'top' }
                                }
                            }
                        });
                    }
                }
                
                initProjectProgress();
                
            } catch (error) {
                console.error('Error loading project:', error);
            }
        }
        
        const projectId = $('#ta-project-progress').data('project-id');
        if (projectId) loadProjectData(projectId);
    }
    
    // Financial Dashboard mit SKR42
    if (document.getElementById('ta-financial-dashboard')) {
        async function loadFinancialData(year) {
            try {
                const response = await fetch(`${ta_ajax.api_url}/financial/${year}`);
                const data = await response.json();
                
                $('#ta-total-income').text(formatCurrency(data.total_income));
                $('#ta-total-expenses').text(formatCurrency(data.total_expenses));
                $('#ta-balance').text(formatCurrency(data.balance));
                $('#ta-admin-costs').text(formatCurrency(data.admin_costs));
                $('#ta-admin-percent').text(`${data.admin_percent}%`);
                
                // Monthly Chart
                const monthlyCtx = document.getElementById('ta-monthly-chart');
                if (monthlyCtx && data.monthly) {
                    new Chart(monthlyCtx, {
                        type: 'line',
                        data: {
                            labels: ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'],
                            datasets: [
                                {
                                    label: 'Einnahmen',
                                    data: data.monthly.income,
                                    borderColor: '#10b981',
                                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                                    fill: true
                                },
                                {
                                    label: 'Ausgaben',
                                    data: data.monthly.expenses,
                                    borderColor: '#ef4444',
                                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                                    fill: true
                                }
                            ]
                        },
                        options: {
                            responsive: true,
                            interaction: { mode: 'index', intersect: false }
                        }
                    });
                }
                
                // Category Chart
                const categoryCtx = document.getElementById('ta-category-chart');
                if (categoryCtx && data.categories) {
                    new Chart(categoryCtx, {
                        type: 'doughnut',
                        data: {
                            labels: data.categories.map(c => c.name),
                            datasets: [{
                                data: data.categories.map(c => c.amount),
                                backgroundColor: ['#3b82f6', '#ef4444', '#f59e0b', '#10b981', '#8b5cf6']
                            }]
                        }
                    });
                }
                
                // SKR42 Tabelle
                if (data.skr42_accounts) {
                    let tableHtml = '';
                    data.skr42_accounts.forEach(account => {
                        tableHtml += `
                            <tr>
                                <td>${account.account_number}</td>
                                <td>${account.name}</td>
                                <td class="ta-debit">${account.debit ? formatCurrency(account.debit) : '-'}</td>
                                <td class="ta-credit">${account.credit ? formatCurrency(account.credit) : '-'}</td>
                                <td class="ta-balance ${account.balance >= 0 ? 'positive' : 'negative'}">
                                    ${formatCurrency(account.balance)}
                                </td>
                            </tr>
                        `;
                    });
                    $('#ta-skr42-table-body').html(tableHtml);
                }
                
                $('.ta-finance-container').fadeIn();
                $('.ta-loading').hide();
                
            } catch (error) {
                console.error('Error loading financials:', error);
            }
        }
        
        const year = $('#ta-financial-dashboard').data('year');
        loadFinancialData(year);
        
        $('#ta-year-select').on('change', function() {
            loadFinancialData($(this).val());
        });
    }
    
    // Hilfsfunktionen
    function formatCurrency(amount) {
        return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(amount);
    }
});
