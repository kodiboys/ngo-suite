// FILE: wp-plugin/assets/js/frontend-vue.js
// MODULE: Vue.js Frontend für Donation Form & Projects Display

// Vue 3 CDN
const { createApp, ref, reactive, computed, onMounted } = Vue;

// ==================== Donation Form Component ====================

const DonationForm = {
    props: ['projectId', 'buttonText', 'amounts', 'currency'],
    setup(props) {
        const amount = ref(25);
        const customAmount = ref('');
        const donorName = ref('');
        const donorEmail = ref('');
        const paymentMethod = ref('stripe');
        const isLoading = ref(false);
        const error = ref(null);
        const success = ref(false);
        
        const amountOptions = computed(() => {
            return props.amounts.split(',').map(a => parseFloat(a));
        });
        
        const displayAmount = computed(() => {
            if (customAmount.value) {
                return parseFloat(customAmount.value);
            }
            return amount.value;
        });
        
        const selectAmount = (value) => {
            amount.value = value;
            customAmount.value = '';
        };
        
        const handleSubmit = async () => {
            isLoading.value = true;
            error.value = null;
            
            const donationData = {
                amount: displayAmount.value,
                donor_name: donorName.value,
                donor_email: donorEmail.value,
                project_id: props.projectId,
                payment_provider: paymentMethod.value,
                success_url: window.location.href + '?donation=success',
                cancel_url: window.location.href + '?donation=cancel'
            };
            
            try {
                const response = await fetch(trueangels_frontend.rest_url + '/donations', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-WP-Nonce': trueangels_frontend.rest_nonce
                    },
                    body: JSON.stringify(donationData)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    success.value = true;
                    
                    // Redirect to payment page if needed
                    if (result.redirect_url) {
                        window.location.href = result.redirect_url;
                    } else if (result.client_secret && paymentMethod.value === 'stripe') {
                        // Handle Stripe payment
                        await handleStripePayment(result.client_secret);
                    }
                } else {
                    error.value = result.error || 'Payment failed';
                }
            } catch (err) {
                error.value = 'Network error. Please try again.';
                console.error(err);
            } finally {
                isLoading.value = false;
            }
        };
        
        const handleStripePayment = async (clientSecret) => {
            // Load Stripe.js
            const stripe = Stripe(trueangels_frontend.stripe_key);
            const { error } = await stripe.confirmPayment({
                clientSecret,
                confirmParams: {
                    return_url: window.location.href + '?donation=success'
                }
            });
            
            if (error) {
                error.value = error.message;
            }
        };
        
        return {
            amount,
            customAmount,
            donorName,
            donorEmail,
            paymentMethod,
            isLoading,
            error,
            success,
            amountOptions,
            displayAmount,
            selectAmount,
            handleSubmit
        };
    },
    template: `
        <div class="trueangels-donation-form">
            <div v-if="success" class="trueangels-success-message">
                <h3>Vielen Dank für Ihre Spende! 🙏</h3>
                <p>Ihre Spende wurde erfolgreich verarbeitet. Sie erhalten eine Bestätigung per E-Mail.</p>
            </div>
            
            <div v-else>
                <div class="trueangels-amount-section">
                    <label class="trueangels-label">Spendenbetrag</label>
                    <div class="trueangels-amount-buttons">
                        <button v-for="opt in amountOptions" 
                                :key="opt"
                                @click="selectAmount(opt)"
                                :class="{ active: amount === opt && !customAmount }"
                                class="trueangels-amount-btn">
                            {{ currency }} {{ opt }}
                        </button>
                        <div class="trueangels-custom-amount">
                            <input type="number" 
                                   v-model="customAmount"
                                   placeholder="Benutzerdefiniert"
                                   class="trueangels-input">
                        </div>
                    </div>
                </div>
                
                <div class="trueangels-donor-section">
                    <div class="trueangels-field">
                        <label class="trueangels-label">Ihr Name (optional)</label>
                        <input type="text" v-model="donorName" class="trueangels-input">
                    </div>
                    
                    <div class="trueangels-field">
                        <label class="trueangels-label">E-Mail *</label>
                        <input type="email" v-model="donorEmail" required class="trueangels-input">
                    </div>
                </div>
                
                <div class="trueangels-payment-section">
                    <label class="trueangels-label">Zahlungsmethode</label>
                    <div class="trueangels-payment-methods">
                        <label class="trueangels-radio">
                            <input type="radio" value="stripe" v-model="paymentMethod">
                            <span>💳 Kreditkarte</span>
                        </label>
                        <label class="trueangels-radio">
                            <input type="radio" value="paypal" v-model="paymentMethod">
                            <span>💰 PayPal</span>
                        </label>
                        <label class="trueangels-radio">
                            <input type="radio" value="klarna" v-model="paymentMethod">
                            <span>🏦 Klarna</span>
                        </label>
                    </div>
                </div>
                
                <div v-if="error" class="trueangels-error">
                    {{ error }}
                </div>
                
                <button @click="handleSubmit" 
                        :disabled="isLoading || !donorEmail"
                        class="trueangels-submit-btn">
                    <span v-if="isLoading">Verarbeitung...</span>
                    <span v-else>{{ buttonText }}</span>
                </button>
            </div>
        </div>
    `
};

// ==================== Projects Grid Component ====================

const ProjectsGrid = {
    props: ['limit', 'showProgress', 'layout'],
    setup(props) {
        const projects = ref([]);
        const isLoading = ref(true);
        const error = ref(null);
        
        onMounted(async () => {
            try {
                const response = await fetch(trueangels_frontend.rest_url + '/projects');
                const data = await response.json();
                projects.value = props.limit ? data.slice(0, props.limit) : data;
            } catch (err) {
                error.value = 'Failed to load projects';
                console.error(err);
            } finally {
                isLoading.value = false;
            }
        });
        
        const formatCurrency = (amount) => {
            return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(amount);
        };
        
        return {
            projects,
            isLoading,
            error,
            formatCurrency
        };
    },
    template: `
        <div v-if="isLoading" class="trueangels-loading">
            <div class="trueangels-spinner"></div>
            <p>Projekte werden geladen...</p>
        </div>
        
        <div v-else-if="error" class="trueangels-error">
            {{ error }}
        </div>
        
        <div v-else :class="['trueangels-projects', layout === 'grid' ? 'trueangels-projects-grid' : 'trueangels-projects-list']">
            <div v-for="project in projects" :key="project.id" class="trueangels-project-card">
                <div class="trueangels-project-header">
                    <h3>{{ project.name }}</h3>
                    <span class="trueangels-project-amount">{{ formatCurrency(project.donations_total) }}</span>
                </div>
                
                <p class="trueangels-project-description">{{ project.description }}</p>
                
                <div v-if="showProgress === 'yes'" class="trueangels-project-progress">
                    <div class="trueangels-progress-bar">
                        <div class="trueangels-progress-fill" :style="{ width: project.progress + '%' }"></div>
                    </div>
                    <div class="trueangels-progress-stats">
                        <span>{{ project.progress }}% finanziert</span>
                        <span>Ziel: {{ formatCurrency(project.budget_total) }}</span>
                    </div>
                </div>
                
                <button class="trueangels-donate-btn" @click="alert('Donation form coming soon')">
                    Jetzt spenden
                </button>
            </div>
        </div>
    `
};

// ==================== Campaign Widget Component ====================

const CampaignWidget = {
    props: ['campaignId'],
    setup(props) {
        const campaign = ref(null);
        const isLoading = ref(true);
        
        onMounted(async () => {
            if (props.campaignId) {
                try {
                    const response = await fetch(trueangels_frontend.rest_url + '/campaigns/' + props.campaignId);
                    campaign.value = await response.json();
                } catch (err) {
                    console.error(err);
                } finally {
                    isLoading.value = false;
                }
            }
        });
        
        const formatCurrency = (amount) => {
            return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(amount);
        };
        
        return {
            campaign,
            isLoading,
            formatCurrency
        };
    },
    template: `
        <div v-if="isLoading" class="trueangels-loading-spinner"></div>
        <div v-else-if="campaign" class="trueangels-campaign-content">
            <div class="trueangels-campaign-progress">
                <div class="trueangels-progress-bar">
                    <div class="trueangels-progress-fill" :style="{ width: campaign.progress + '%' }"></div>
                </div>
                <div class="trueangels-campaign-stats">
                    <span class="trueangels-raised">{{ formatCurrency(campaign.raised) }}</span>
                    <span class="trueangels-goal">von {{ formatCurrency(campaign.goal) }}</span>
                </div>
            </div>
            <button class="trueangels-donate-btn">Jetzt unterstützen</button>
        </div>
    `
};

// ==================== Initialize Vue Apps ====================

document.addEventListener('DOMContentLoaded', () => {
    // Donation Form
    const donationRoot = document.getElementById('trueangels-donation-form-root');
    if (donationRoot) {
        const app = createApp(DonationForm, {
            projectId: donationRoot.dataset.projectId,
            buttonText: donationRoot.dataset.buttonText,
            amounts: donationRoot.dataset.amounts,
            currency: donationRoot.dataset.currency
        });
        app.mount('#trueangels-donation-form-root');
    }
    
    // Projects Grid
    const projectsRoot = document.getElementById('trueangels-projects-root');
    if (projectsRoot) {
        const app = createApp(ProjectsGrid, {
            limit: projectsRoot.dataset.limit,
            showProgress: projectsRoot.dataset.showProgress,
            layout: projectsRoot.dataset.layout
        });
        app.mount('#trueangels-projects-root');
    }
    
    // Campaign Widget
    const campaignRoot = document.getElementById('trueangels-campaign-root');
    if (campaignRoot) {
        const app = createApp(CampaignWidget, {
            campaignId: campaignRoot.dataset.campaignId
        });
        app.mount('#trueangels-campaign-root');
    }
});