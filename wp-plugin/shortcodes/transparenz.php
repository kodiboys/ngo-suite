<?php
/**
 * FILE: wp-plugin/shortcodes/transparenz.php
 * MODULE: WordPress Shortcodes für Transparenz-Dashboard & Bedarfe
 * 
 * Shortcodes:
 * - [transparenz_dashboard jahr="2026" projekt="bucha"]
 * - [trueangels_projekteliste limit="6" kat="ukraine"]
 * - [trueangels_bedarfeliste projekt="bucha" kat="wohnen"]
 */

// Prevent direct access
if (!defined('ABSPATH')) {
    exit;
}

/**
 * Shortcode: Transparenz Dashboard
 * Zeigt KPI-Cards, Timeline-Chart und Spendentabelle
 * 
 * @param array $atts {
 *     Attributes for the shortcode.
 *     
 *     @type string $jahr    Jahr für Filter (default: aktuelles Jahr)
 *     @type string $projekt Projektname oder ID (optional)
 *     @type string $kat     Kategorie (optional)
 *     @type int    $limit   Anzahl Spenden in Tabelle (default: 50)
 * }
 */
function trueangels_transparenz_dashboard_shortcode($atts) {
    $atts = shortcode_atts([
        'jahr' => date('Y'),
        'projekt' => '',
        'kat' => '',
        'limit' => 50
    ], $atts);
    
    $api_url = TRUEANGELS_API_URL . '/api/v1/transparenz';
    $query_params = http_build_query([
        'jahr' => $atts['jahr'],
        'projekt' => $atts['projekt'],
        'kat' => $atts['kat'],
        'limit' => $atts['limit']
    ]);
    
    $response = wp_remote_get($api_url . '?' . $query_params, [
        'headers' => [
            'Authorization' => 'Bearer ' . TRUEANGELS_API_KEY
        ],
        'timeout' => 30
    ]);
    
    if (is_wp_error($response)) {
        return '<div class="trueangels-error">❌ Transparenz-Daten konnten nicht geladen werden.</div>';
    }
    
    $data = json_decode(wp_remote_retrieve_body($response), true);
    
    if (!$data || isset($data['error'])) {
        return '<div class="trueangels-error">❌ Fehler beim Laden der Transparenz-Daten.</div>';
    }
    
    ob_start();
    ?>
    <div class="trueangels-transparenz-dashboard" 
         data-jahr="<?php echo esc_attr($atts['jahr']); ?>"
         data-projekt="<?php echo esc_attr($atts['projekt']); ?>">
        
        <!-- Filter Bar -->
        <div class="trueangels-filter-bar">
            <div class="trueangels-filter-group">
                <label>📅 Jahr</label>
                <select id="trueangels-filter-year" class="trueangels-filter-select">
                    <?php for ($y = 2020; $y <= date('Y'); $y++): ?>
                        <option value="<?php echo $y; ?>" <?php selected($y, $atts['jahr']); ?>>
                            <?php echo $y; ?>
                        </option>
                    <?php endfor; ?>
                </select>
            </div>
            
            <div class="trueangels-filter-group">
                <label>🏗️ Projekt</label>
                <input type="text" 
                       id="trueangels-filter-project" 
                       class="trueangels-filter-input" 
                       placeholder="Alle Projekte"
                       value="<?php echo esc_attr($atts['projekt']); ?>">
            </div>
            
            <button id="trueangels-filter-apply" class="trueangels-filter-btn">
                🔄 Aktualisieren
            </button>
        </div>
        
        <!-- KPI Cards -->
        <div class="trueangels-kpi-grid">
            <div class="trueangels-kpi-card">
                <div class="trueangels-kpi-icon">💰</div>
                <div class="trueangels-kpi-value">
                    <?php echo number_format($data['metrics']['total_incoming'], 0, ',', '.'); ?> €
                </div>
                <div class="trueangels-kpi-label">Gesamteingänge</div>
            </div>
            
            <div class="trueangels-kpi-card">
                <div class="trueangels-kpi-icon">📊</div>
                <div class="trueangels-kpi-value">
                    <?php echo number_format($data['metrics']['total_outgoing'], 0, ',', '.'); ?> €
                </div>
                <div class="trueangels-kpi-label">Gesamtausgaben</div>
            </div>
            
            <div class="trueangels-kpi-card">
                <div class="trueangels-kpi-icon">🎯</div>
                <div class="trueangels-kpi-value">
                    <?php echo $data['metrics']['project_progress']; ?>%
                </div>
                <div class="trueangels-kpi-label">Projektfortschritt</div>
                <div class="trueangels-progress-bar">
                    <div class="trueangels-progress-fill" 
                         style="width: <?php echo $data['metrics']['project_progress']; ?>%"></div>
                </div>
            </div>
            
            <div class="trueangels-kpi-card">
                <div class="trueangels-kpi-icon">👥</div>
                <div class="trueangels-kpi-value">
                    <?php echo number_format($data['metrics']['donor_count'], 0, ',', '.'); ?>
                </div>
                <div class="trueangels-kpi-label">Spender</div>
            </div>
            
            <div class="trueangels-kpi-card">
                <div class="trueangels-kpi-icon">💝</div>
                <div class="trueangels-kpi-value">
                    <?php echo number_format($data['metrics']['donation_count'], 0, ',', '.'); ?>
                </div>
                <div class="trueangels-kpi-label">Spenden</div>
            </div>
            
            <div class="trueangels-kpi-card">
                <div class="trueangels-kpi-icon">⭐</div>
                <div class="trueangels-kpi-value">
                    <?php echo number_format($data['metrics']['avg_donation'], 2, ',', '.'); ?> €
                </div>
                <div class="trueangels-kpi-label">Durchschnitt</div>
            </div>
        </div>
        
        <!-- Timeline Chart (Chart.js) -->
        <div class="trueangels-chart-container">
            <h3>📈 Entwicklung der Spenden</h3>
            <canvas id="trueangels-timeline-chart" 
                    width="800" 
                    height="400"
                    data-timeline='<?php echo json_encode($data['timeline']); ?>'></canvas>
        </div>
        
        <!-- Spendentabelle (pseudonymisiert) -->
        <div class="trueangels-table-container">
            <h3>📋 Letzte Spenden</h3>
            <div class="trueangels-merkle-badge">
                🔒 Merkle-Root: <code><?php echo substr($data['merkle_root'], 0, 16); ?>...</code>
                <span class="trueangels-tooltip" title="Manipulationssicherer Hash der Transparenz-Daten">
                    ⓘ
                </span>
            </div>
            
            <table class="trueangels-transparency-table">
                <thead>
                    <tr>
                        <th>Spender</th>
                        <th>Datum</th>
                        <th>Projekt</th>
                        <th>Betrag</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($data['donations'] as $donation): ?>
                    <tr>
                        <td class="trueangels-donor-hash">
                            <?php echo esc_html($donation['donor_hash']); ?>
                        </td>
                        <td><?php echo esc_html($donation['date']); ?></td>
                        <td><?php echo esc_html($donation['project_name']); ?></td>
                        <td class="trueangels-amount">
                            <?php echo number_format($donation['amount'], 2, ',', '.'); ?> €
                        </td>
                    </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
            
            <div class="trueangels-update-info">
                Letzte Aktualisierung: <?php echo date('d.m.Y H:i', strtotime($data['last_updated'])); ?>
            </div>
        </div>
    </div>
    
    <script>
    jQuery(document).ready(function($) {
        // Chart.js initialisieren
        var ctx = document.getElementById('trueangels-timeline-chart').getContext('2d');
        var timelineData = <?php echo json_encode($data['timeline']); ?>;
        
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: timelineData.map(d => d.month),
                datasets: [
                    {
                        label: 'Eingänge (€)',
                        data: timelineData.map(d => d.incoming),
                        borderColor: '#2d6a4f',
                        backgroundColor: 'rgba(45, 106, 79, 0.1)',
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Ausgaben (€)',
                        data: timelineData.map(d => d.outgoing),
                        borderColor: '#e63946',
                        backgroundColor: 'rgba(230, 57, 70, 0.1)',
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Kumuliert (€)',
                        data: timelineData.map(d => d.cumulative),
                        borderColor: '#1d3557',
                        borderDash: [5, 5],
                        fill: false,
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.dataset.label + ': ' + 
                                       context.raw.toLocaleString('de-DE') + ' €';
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        ticks: {
                            callback: function(value) {
                                return value.toLocaleString('de-DE') + ' €';
                            }
                        }
                    }
                }
            }
        });
        
        // Filter Funktionalität
        $('#trueangels-filter-apply').on('click', function() {
            var year = $('#trueangels-filter-year').val();
            var project = $('#trueangels-filter-project').val();
            var currentUrl = window.location.href.split('?')[0];
            window.location.href = currentUrl + '?jahr=' + year + '&projekt=' + encodeURIComponent(project);
        });
    });
    </script>
    <?php
    return ob_get_clean();
}
add_shortcode('transparenz_dashboard', 'trueangels_transparenz_dashboard_shortcode');


/**
 * Shortcode: Projektliste mit Bedarfen
 * Zeigt Projekte als Cards mit Fortschrittsbalken und Spenden-Buttons
 * 
 * @param array $atts {
 *     @type int    $limit  Maximale Anzahl Projekte (default: 6)
 *     @type string $kat    Kategorie-Filter (optional)
 *     @type string $status Status-Filter (active/completed)
 * }
 */
function trueangels_projekteliste_shortcode($atts) {
    $atts = shortcode_atts([
        'limit' => 6,
        'kat' => '',
        'status' => 'active'
    ], $atts);
    
    $api_url = TRUEANGELS_API_URL . '/api/v1/transparenz/projects';
    $query_params = http_build_query([
        'limit' => $atts['limit'],
        'status' => $atts['status']
    ]);
    
    $response = wp_remote_get($api_url . '?' . $query_params, [
        'headers' => ['Authorization' => 'Bearer ' . TRUEANGELS_API_KEY],
        'timeout' => 30
    ]);
    
    if (is_wp_error($response)) {
        return '<div class="trueangels-error">❌ Projekte konnten nicht geladen werden.</div>';
    }
    
    $projects = json_decode(wp_remote_retrieve_body($response), true);
    
    if (!$projects || isset($projects['error'])) {
        return '<div class="trueangels-error">❌ Keine Projekte gefunden.</div>';
    }
    
    ob_start();
    ?>
    <div class="trueangels-projects-grid">
        <?php foreach ($projects as $project): ?>
        <div class="trueangels-project-card">
            <?php if (!empty($project['image_url'])): ?>
                <img src="<?php echo esc_url($project['image_url']); ?>" 
                     alt="<?php echo esc_attr($project['name']); ?>"
                     class="trueangels-project-image">
            <?php else: ?>
                <div class="trueangels-project-icon">🏗️</div>
            <?php endif; ?>
            
            <h3 class="trueangels-project-title"><?php echo esc_html($project['name']); ?></h3>
            <p class="trueangels-project-description"><?php echo esc_html($project['description']); ?></p>
            
            <div class="trueangels-project-stats">
                <div class="trueangels-stat">
                    <span class="trueangels-stat-label">Budget</span>
                    <span class="trueangels-stat-value">
                        <?php echo number_format($project['budget_total'], 0, ',', '.'); ?> €
                    </span>
                </div>
                <div class="trueangels-stat">
                    <span class="trueangels-stat-label">Spenden</span>
                    <span class="trueangels-stat-value">
                        <?php echo number_format($project['donations_total'], 0, ',', '.'); ?> €
                    </span>
                </div>
                <div class="trueangels-stat">
                    <span class="trueangels-stat-label">Spender</span>
                    <span class="trueangels-stat-value"><?php echo $project['donor_count']; ?></span>
                </div>
            </div>
            
            <div class="trueangels-progress-section">
                <div class="trueangels-progress-label">
                    <span>Fortschritt</span>
                    <span><?php echo $project['progress_percent']; ?>%</span>
                </div>
                <div class="trueangels-progress-bar">
                    <div class="trueangels-progress-fill" 
                         style="width: <?php echo $project['progress_percent']; ?>%"></div>
                </div>
            </div>
            
            <!-- Bedarfe werden per AJAX geladen -->
            <div class="trueangels-needs-container" 
                 data-project-id="<?php echo $project['id']; ?>"
                 data-project-name="<?php echo esc_attr($project['name']); ?>">
                <div class="trueangels-needs-loading">🔄 Bedarfe werden geladen...</div>
            </div>
            
            <button class="trueangels-donate-btn" 
                    onclick="trueangelsOpenDonationModal('<?php echo $project['id']; ?>', '<?php echo esc_js($project['name']); ?>')">
                💝 Jetzt spenden
            </button>
        </div>
        <?php endforeach; ?>
    </div>
    
    <script>
    // Bedarfe per AJAX laden
    jQuery(document).ready(function($) {
        $('.trueangels-needs-container').each(function() {
            var container = $(this);
            var projectId = container.data('project-id');
            var projectName = container.data('project-name');
            
            $.ajax({
                url: '<?php echo TRUEANGELS_API_URL; ?>/api/v1/transparenz/needs/' + projectId,
                method: 'GET',
                headers: {
                    'Authorization': 'Bearer <?php echo TRUEANGELS_API_KEY; ?>'
                },
                success: function(needs) {
                    if (needs.length === 0) {
                        container.html('<div class="trueangels-no-needs">✨ Keine aktuellen Bedarfe</div>');
                        return;
                    }
                    
                    var html = '<div class="trueangels-needs-grid">';
                    needs.slice(0, 3).forEach(function(need) {
                        var priorityIcon = {
                            'critical': '🔴',
                            'high': '🟠',
                            'medium': '🟡',
                            'low': '🟢'
                        }[need.priority] || '⚪';
                        
                        html += `
                            <div class="trueangels-need-item">
                                <div class="trueangels-need-icon">${priorityIcon}</div>
                                <div class="trueangels-need-info">
                                    <div class="trueangels-need-name">${need.name}</div>
                                    <div class="trueangels-need-progress">
                                        <div class="trueangels-mini-progress">
                                            <div class="trueangels-mini-fill" style="width: ${need.progress_percent}%"></div>
                                        </div>
                                        <div class="trueangels-need-stats">
                                            ${need.quantity_current}/${need.quantity_target} ${need.unit || 'Stk'}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    html += '</div>';
                    container.html(html);
                },
                error: function() {
                    container.html('<div class="trueangels-needs-error">⚠️ Bedarfe konnten nicht geladen werden</div>');
                }
            });
        });
    });
    </script>
    <?php
    return ob_get_clean();
}
add_shortcode('trueangels_projekteliste', 'trueangels_projekteliste_shortcode');


/**
 * Shortcode: Bedarfeliste für ein Projekt
 * Zeigt detaillierte Bedarfe als Grid mit Fortschritt und Icons
 * 
 * @param array $atts {
 *     @type string $projekt Projektname oder ID (erforderlich)
 *     @type string $kat     Kategorie-Filter (optional)
 * }
 */
function trueangels_bedarfeliste_shortcode($atts) {
    $atts = shortcode_atts([
        'projekt' => '',
        'kat' => ''
    ], $atts);
    
    if (empty($atts['projekt'])) {
        return '<div class="trueangels-error">❌ Bitte geben Sie ein Projekt an (projekt="name").</div>';
    }
    
    // Hole Projekt-ID
    $projects_url = TRUEANGELS_API_URL . '/api/v1/transparenz/projects';
    $response = wp_remote_get($projects_url, [
        'headers' => ['Authorization' => 'Bearer ' . TRUEANGELS_API_KEY]
    ]);
    
    if (is_wp_error($response)) {
        return '<div class="trueangels-error">❌ Projekt konnte nicht gefunden werden.</div>';
    }
    
    $projects = json_decode(wp_remote_retrieve_body($response), true);
    $project_id = null;
    $project_name = $atts['projekt'];
    
    foreach ($projects as $proj) {
        if (strtolower($proj['name']) === strtolower($atts['projekt']) || $proj['id'] === $atts['projekt']) {
            $project_id = $proj['id'];
            $project_name = $proj['name'];
            break;
        }
    }
    
    if (!$project_id) {
        return '<div class="trueangels-error">❌ Projekt "' . esc_html($atts['projekt']) . '" nicht gefunden.</div>';
    }
    
    // Hole Bedarfe
    $needs_url = TRUEANGELS_API_URL . '/api/v1/transparenz/needs/' . $project_id;
    if (!empty($atts['kat'])) {
        $needs_url .= '?category=' . urlencode($atts['kat']);
    }
    
    $response = wp_remote_get($needs_url, [
        'headers' => ['Authorization' => 'Bearer ' . TRUEANGELS_API_KEY]
    ]);
    
    if (is_wp_error($response)) {
        return '<div class="trueangels-error">❌ Bedarfe konnten nicht geladen werden.</div>';
    }
    
    $needs = json_decode(wp_remote_retrieve_body($response), true);
    
    if (!$needs || empty($needs)) {
        return '<div class="trueangels-info">✨ Keine aktuellen Bedarfe für ' . esc_html($project_name) . '.</div>';
    }
    
    // Kategorien für Filter
    $categories = array_unique(array_column($needs, 'category'));
    
    $priority_labels = [
        'critical' => ['label' => 'Kritisch', 'class' => 'priority-critical'],
        'high' => ['label' => 'Hoch', 'class' => 'priority-high'],
        'medium' => ['label' => 'Mittel', 'class' => 'priority-medium'],
        'low' => ['label' => 'Niedrig', 'class' => 'priority-low']
    ];
    
    $category_icons = [
        'wohnen' => '🏠',
        'nahrung' => '🍲',
        'medizin' => '💊',
        'kleidung' => '👕',
        'transport' => '🚗',
        'energie' => '⚡',
        'sonstige' => '📦'
    ];
    
    ob_start();
    ?>
    <div class="trueangels-needs-dashboard" data-project-id="<?php echo $project_id; ?>">
        <h2>📋 Bedarfe für <?php echo esc_html($project_name); ?></h2>
        
        <!-- Kategorie-Filter -->
        <?php if (count($categories) > 1): ?>
        <div class="trueangels-needs-filter">
            <button class="trueangels-filter-chip active" data-category="all">Alle</button>
            <?php foreach ($categories as $cat): ?>
                <button class="trueangels-filter-chip" data-category="<?php echo esc_attr($cat); ?>">
                    <?php echo $category_icons[$cat] ?? '📌'; ?> <?php echo ucfirst($cat); ?>
                </button>
            <?php endforeach; ?>
        </div>
        <?php endif; ?>
        
        <!-- Needs Grid -->
        <div class="trueangels-needs-grid-detailed">
            <?php foreach ($needs as $need): 
                $priority = $priority_labels[$need['priority']] ?? $priority_labels['medium'];
                $remaining = $need['quantity_remaining'];
                $is_completed = $remaining <= 0;
                $status_class = $is_completed ? 'need-completed' : '';
            ?>
            <div class="trueangels-need-card <?php echo $status_class; ?>" data-category="<?php echo $need['category']; ?>">
                <div class="trueangels-need-header">
                    <div class="trueangels-need-icon">
                        <?php echo $category_icons[$need['category']] ?? '📦'; ?>
                    </div>
                    <div class="trueangels-need-title">
                        <h4><?php echo esc_html($need['name']); ?></h4>
                        <span class="trueangels-need-priority <?php echo $priority['class']; ?>">
                            <?php echo $priority['label']; ?>
                        </span>
                    </div>
                </div>
                
                <?php if (!empty($need['description'])): ?>
                    <p class="trueangels-need-description"><?php echo esc_html($need['description']); ?></p>
                <?php endif; ?>
                
                <div class="trueangels-need-stats-detailed">
                    <div class="trueangels-need-progress-circle">
                        <svg viewBox="0 0 36 36" class="trueangels-circular-chart">
                            <path class="trueangels-circle-bg"
                                d="M18 2.0845
                                a 15.9155 15.9155 0 0 1 0 31.831
                                a 15.9155 15.9155 0 0 1 0 -31.831"
                            />
                            <path class="trueangels-circle-progress"
                                stroke-dasharray="<?php echo $need['progress_percent']; ?>, 100"
                                d="M18 2.0845
                                a 15.9155 15.9155 0 0 1 0 31.831
                                a 15.9155 15.9155 0 0 1 0 -31.831"
                            />
                            <text x="18" y="20.35" class="trueangels-progress-text">
                                <?php echo round($need['progress_percent']); ?>%
                            </text>
                        </svg>
                    </div>
                    
                    <div class="trueangels-need-quantity">
                        <div class="trueangels-quantity-current">
                            <?php echo number_format($need['quantity_current'], 0, ',', '.'); ?>
                        </div>
                        <div class="trueangels-quantity-separator">/</div>
                        <div class="trueangels-quantity-target">
                            <?php echo number_format($need['quantity_target'], 0, ',', '.'); ?>
                        </div>
                        <div class="trueangels-quantity-unit">
                            <?php echo $need['unit'] ?? 'Stk'; ?>
                        </div>
                    </div>
                </div>
                
                <?php if ($is_completed): ?>
                    <div class="trueangels-need-completed-badge">✅ Erfüllt</div>
                <?php else: ?>
                    <div class="trueangels-need-remaining">
                        Noch benötigt: <?php echo number_format($remaining, 0, ',', '.'); ?> <?php echo $need['unit'] ?? 'Stk'; ?>
                    </div>
                <?php endif; ?>
                
                <button class="trueangels-donate-need-btn" 
                        onclick="trueangelsOpenDonationModal('<?php echo $project_id; ?>', '<?php echo esc_js($need['name']); ?>', <?php echo $need['unit_price_eur'] ?? 'null'; ?>)">
                    💝 Für diesen Bedarf spenden
                </button>
            </div>
            <?php endforeach; ?>
        </div>
    </div>
    
    <script>
    jQuery(document).ready(function($) {
        // Kategorie-Filter
        $('.trueangels-filter-chip').on('click', function() {
            var category = $(this).data('category');
            
            $('.trueangels-filter-chip').removeClass('active');
            $(this).addClass('active');
            
            if (category === 'all') {
                $('.trueangels-need-card').show();
            } else {
                $('.trueangels-need-card').hide();
                $('.trueangels-need-card[data-category="' + category + '"]').show();
            }
        });
    });
    </script>
    <?php
    return ob_get_clean();
}
add_shortcode('trueangels_bedarfeliste', 'trueangels_bedarfeliste_shortcode');