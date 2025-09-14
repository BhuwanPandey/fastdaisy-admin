// Handle logout

$(document).on('click', '#logout', function () {
  $.ajax({
    url: $(this).attr('data-url'),
    method: 'POST',
    success: function (result) {
      window.location.href = result.redirect_url;
    },
    error: function (request, status, error) {
      alert(request.responseText);
    }
  });
});


// Search
$(document).on('click', '#search-button', function () {
  var searchTerm = encodeURIComponent($("#search-input").val());

  newUrl = "";
  if (window.location.search && window.location.search.indexOf('search=') != -1) {
    newUrl = window.location.search.replace(/search=[^&]*/, "search=" + searchTerm);
  } else if (window.location.search) {
    newUrl = window.location.search + "&search=" + searchTerm;
  } else {
    newUrl = window.location.search + "?search=" + searchTerm;
  }
  window.location.href = newUrl;
});



// Date picker
$(':input[data-role="datepicker"]:not([readonly])').each(function () {
  $(this).flatpickr({
    enableTime: false,
    allowInput: true,
    dateFormat: "Y-m-d",
  });
});

// DateTime picker
$(':input[data-role="datetimepicker"]:not([readonly])').each(function () {
  $(this).flatpickr({
    enableTime: true,
    allowInput: true,
    enableSeconds: true,
    time_24hr: true,
    dateFormat: "Y-m-d H:i:s",
  });
});


// Checkbox select
$("#select-all").click(function () {
  $('input.select-box:checkbox').prop('checked', this.checked);
});

// Bulk delete
$("#action-delete").click(function () {
  var pks = [];
  $('.select-box').each(function () {
    if ($(this).is(':checked')) {
      pks.push($(this).siblings().get(0).value);
    }
  });

  $('#action-delete').data("pk", pks);
  $('#action-delete').data("url", $(this).data('url') + '?pks=' + pks.join(","));
  $('#modal-delete').modal('show');
});


$(document).ready(function () {

function submit_search_form() {
    let search_val = $('#list-form #searchbar').val()
    $('#hidden-search-form #searchbar').val(search_val)
    $('#hidden-search-form form').submit()
}

$('#list-form #searchbar').keydown(function (event) {
if (event.key === "Enter") {
    event.preventDefault()
    submit_search_form()
}
})
$('#list-form .search-submit').click(submit_search_form)

const $selectAll = $('#select-all');
const $boxes = $('input.checkbox');

$boxes.on('change', function () {
  const allChecked = $boxes.length === $boxes.filter(':checked').length;
  $selectAll.prop('checked', allChecked);
});


$('.filter-select').each(function (i, elem) {
    let maxItems = 1
    if ($(elem).is('[multiple]')) {
        maxItems = null
    }
    new TomSelect(elem, {
        plugins: ['remove_button'],
        create: false,
        maxItems: maxItems,
        maxOptions: null,
    });
})

const extractValueFromQueryString = (queryString, dataKey) => {
        try {
            const params = new URLSearchParams(queryString);
            for (const [key, value] of params) {
                if (key.startsWith(dataKey)) {
                    return value;
                }
            }
            return null;
        } catch (error) {
            console.error('Error parsing query string:', error);
            return null;
        }
    };

const buildQueryString = (queryObj) => {
        const queryArray = Object.entries(queryObj)
            .flatMap(([key, values]) => {
                if (Array.isArray(values)) {
                    const validValues = values.filter(
                        (item) => item != null && item !== ''
                    );
                    if (validValues.length > 0) {
                        return validValues.map(item => `${encodeURIComponent(key)}=${encodeURIComponent(item)}`);
                    }
                }
                return null;
            })
            .filter(Boolean);
        return queryArray.length ? `?${queryArray.join('&')}` : '';
    };

  
const applyFilters = () => {
  const filterData = {};
  document.querySelectorAll('.filter-select').forEach((select) => {
      // Handle both single and multiple select elements
      let selectedValues = [];

      if (select.multiple) {
          // Multiple select: get all selected options
          selectedValues = Array.from(select.selectedOptions || [])
              .map((option) => option.value)
              .filter((value) => value != null && value !== '');
      } else {
          // Single select: get the selected value
          const value = select.value;
          if (value != null && value !== '') {
              selectedValues = [value];
          }
      }

      const dataKeys = select.dataset.keys?.split(',').filter(Boolean) || [];
      
      dataKeys.forEach((key) => {
          if (selectedValues.length) {
              const values = selectedValues
                  .map((value) => extractValueFromQueryString(value, key))
                  .filter(Boolean);
                  let formattedKey = key
                  
                  
              // if (select.multiple) {
              //     formattedKey = key.replace('__exact', '__in');
              //     if (!formattedKey.match(/__[^_]+$/)) {
              //         formattedKey += '__in';
              //     }
              // }
              if (values.length) {
                  filterData[formattedKey] = filterData[formattedKey]
                      ? [...filterData[formattedKey], ...values]
                      : values;
              }
          }
      });
      let queryString = buildQueryString(filterData);
      window.location.href = queryString || '?';

  });
}


const applyButton = document.getElementById('apply-filter');
if (applyButton) {
    applyButton.addEventListener('click', applyFilters);
}


});

$(document).on('click', '.cancel-link', function (e) {
  e.preventDefault();
  window.history.back();
});

